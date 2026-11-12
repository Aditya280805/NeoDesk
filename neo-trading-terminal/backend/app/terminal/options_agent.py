"""Agno options agent with evidence, execution budgets and user-scoped traces."""
import asyncio
import json
import logging
import time
from collections import deque
from contextlib import nullcontext
from datetime import UTC, datetime
from threading import Lock, Event
from uuid import uuid4

from fastapi import HTTPException

from app.terminal.agent_registry import register_agent, list_agents
from app.terminal.agent_scope import PortfolioChatRequest, AgentAnswer, ReportAnswer, report_scope
from app.terminal.options_report_context import REPORT_KINDS, load_report, bounded_report
from app.terminal.options_snapshot import ChatRequest, OptionsContext, SnapshotService, normalize_snapshot
from app.terminal.options_mcp import OptionsMCP, TOOL_VERSION
from app.terminal.portfolio_risk_store import RiskStoreBusyError
from app.terminal.portfolio_risk_diagnostics import risk_diagnostics
from app.terminal.options_model import build_model, close_agent_model, options_run, provider_failure, provider_settings
from app.terminal.agent_harness import RequestHarness, harness_context, current_harness, bounded_context, HarnessError
from app.terminal.agent_scope import specialist_scope
from app.terminal.agent_registry import get_agent
from app.terminal import specialist_agents  # register fresh specialist factories
from app.terminal import unified_chat  # register master_router factory

RUN_CONTRACT_VERSION = 'snapshot.1'
logger = logging.getLogger(__name__)


class OptionsAgent:
    deadline_seconds = 60

    def __init__(self, config, store, market, *, portfolio_service=None, risk_store=None):
        from app.terminal.unified_chat import RoutingLimiter
        self.config, self.store, self.market = config, store, market
        from app.terminal.portfolio_risk_store import PortfolioRiskStore
        self.risk_store = risk_store if risk_store is not None else PortfolioRiskStore(store)
        self.guard = Lock()
        self.active = set()
        self.workers = {}
        self.recent = deque()
        self.refresh_active = set()
        self.routing_limiter = RoutingLimiter(self)
        self.refresh_last = {}
        self.mcp = OptionsMCP(SnapshotService(market), config.options_mcp_port, portfolio_service=portfolio_service)
        self.analytics_capture = None
        if getattr(config,'analytics_tools_enabled',False):
            from .analytics_capture import AnalyticsCaptureService
            from .analytics_runtime import BoundedWork
            from .analytics_store import AnalyticsStore
            self.analytics_capture = AnalyticsCaptureService(market,AnalyticsStore(store.path),self.mcp.snapshots,
                portfolio_service,work=BoundedWork(pending=self.mcp.pending))
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS option_chat_conversations (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    context TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS option_chat_turns (
                    id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL, message TEXT NOT NULL,
                    answer TEXT NOT NULL, evidence TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS option_chat_owner ON option_chat_turns(user_id, conversation_id, id);
                CREATE TABLE IF NOT EXISTS option_agent_runs (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS option_agent_runs_owner ON option_agent_runs(user_id, id);
            ''')

    def status(self):
        provider = provider_settings(self.config)
        return {'configured': provider.configured and self.mcp.ready, 'model_configured': provider.configured,
                'analytics_tools_enabled': bool(getattr(self.config,'analytics_tools_enabled',False)),
                'mcp_ready': self.mcp.ready, 'enabled': self.config.options_agent_enabled,
                'provider': provider.provider, 'api_key_env': provider.key_name,
                'setup_error': provider.error,
                'model': provider.model, 'generation_token_budget': provider.token_budget, 'framework': 'Agno',
                'registered_agents': list_agents(),
                'read_only': True, 'background_monitoring': bool(getattr(getattr(self,'monitoring_service',None),'running',False)),
                'background_monitoring_opt_in': True}

    def _record(self, user_id, run_id, kind, status, started, detail, db=None):
        transactional = db is not None
        detail['duration_ms'] = round((time.monotonic() - started) * 1000)
        provider = provider_settings(self.config)
        detail.update(model=provider.model, provider=provider.provider, generation_token_budget=provider.token_budget,
                      prompt_version=detail.get("prompt_version", RUN_CONTRACT_VERSION), tool_version=TOOL_VERSION)
        with (self.store.connect() if db is None else nullcontext(db)) as db:
            db.execute('INSERT INTO option_agent_runs VALUES (?,?,?,?,?,?)',
                       (run_id, user_id, kind, status, datetime.now(UTC).isoformat(), json.dumps(detail, allow_nan=False)))
        # Never log prompts, provider exception text, tokens or broker credentials.
        if not transactional:
            logger.info('options_run id=%s kind=%s status=%s duration_ms=%s', run_id, kind, status, detail['duration_ms'])

    def run_record(self, user_id, run_id):
        with self.store.connect() as db:
            row = db.execute('SELECT id,kind,status,created_at,detail FROM option_agent_runs WHERE id=? AND user_id=?',
                             (str(run_id), user_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Run not found.')
        return dict(id=row[0], kind=row[1], status=row[2], created_at=row[3], detail=json.loads(row[4]))

    def _release(self, user_id, active):
        def release(_=None):
            with self.guard:
                active.discard(user_id)
        pending = set(self.workers.get(user_id, ()))
        broker = self.mcp.pending.get(user_id)
        if broker: pending.add(broker)
        pending = {task for task in pending if not task.done()}
        if pending:
            def finished(task):
                pending.discard(task)
                if not pending: release()
            for task in tuple(pending): task.add_done_callback(finished)
        else:
            release()

    def _start_worker(self, user_id, function):
        task = asyncio.create_task(asyncio.to_thread(function))
        self.workers.setdefault(user_id, set()).add(task)
        def finished(done):
            tasks = self.workers.get(user_id)
            if tasks is not None:
                tasks.discard(done)
                if not tasks: self.workers.pop(user_id, None)
            if not done.cancelled(): done.exception()
        task.add_done_callback(finished)
        return task

    async def _finish(self, user_id, run_id, kind, state, started, detail, deadline):
        if state == 'completed' or detail.get('failure_reason') == 'risk_store_busy':
            return
        detail = {key: value for key, value in detail.items() if key != 'risk_report_id'}
        if detail.get('risk_diagnostics'):
            diagnostic = dict(detail['risk_diagnostics'])
            if diagnostic['failure_stage'] is None:
                diagnostic.update(outcome='operational_failure', failure_stage=detail['stages'][-1] if detail['stages'] else 'publication')
            detail['risk_diagnostics'] = diagnostic
            logger.info('portfolio_risk %s', json.dumps(diagnostic, allow_nan=False))
        def record():
            if kind == 'chat' and state != 'completed':
                self.store.audit(user_id, 'OPTIONS_CHAT_FAILED', json.dumps({'run_id': run_id,
                    'model': provider_settings(self.config).model, 'status': state}))
            self._record(user_id, run_id, kind, state, started, detail)
        task = self._start_worker(user_id, record)
        if state not in ('cancelled', 'timeout'):
            done, _ = await asyncio.wait({task}, timeout=max(0, deadline-time.monotonic()))
            if done: task.result()

    async def _locked_worker(self, user_id, deadline, operation):
        """Retain admission until lock/transaction work ends, including cancellation."""
        cancelled = Event()
        def work():
            def check():
                if cancelled.is_set() or time.monotonic() >= deadline:
                    raise TimeoutError('Request deadline expired')
            check()
            if not self.market.lock.acquire(timeout=max(0, deadline-time.monotonic())):
                raise TimeoutError('Request deadline expired')
            try:
                check()
                return operation(check)
            finally:
                self.market.lock.release()
        task = self._start_worker(user_id, work)
        try:
            return await asyncio.shield(task)
        except BaseException:
            cancelled.set()
            raise

    async def snapshot(self, user_id, context):
        return await self._snapshot(user_id, context, 'chain')

    async def analytics_snapshot(self,user_id,body):
        from .analytics_runtime import TOOLS_BY_ROLE, TurnBudget
        if type(user_id) is not int or user_id<=0:
            raise HTTPException(401,'Sign in to your individual account.')
        if not getattr(self.config,'analytics_tools_enabled',False):
            raise HTTPException(404,'Analytics snapshots are not enabled.')
        if self.analytics_capture is None:
            raise HTTPException(503,'Analytics capture is unavailable. Restart after enabling it.')
        self.routing_limiter.enter(user_id)
        try:
            captured = await self.analytics_capture.capture(user_id,body.context,
                body.tools or sorted(TOOLS_BY_ROLE[body.role]),budget=TurnBudget(),historical_input=body.historical_input)
            if captured.owner_id!=user_id:
                raise ValueError('Evidence owner mismatch')
            return {'schema_version':'analytics-snapshot.v1','role':body.role,'read_only':True,
                    'evidence':{name:item.model_dump(mode='json') for name,item in captured.for_role(body.role).items()}}
        except TimeoutError:
            raise HTTPException(504,'Analytics capture timed out. Retry after the current request finishes.') from None
        except Exception:
            raise HTTPException(503,'Analytics evidence could not be captured. Check your broker session and market selection.') from None
        finally:
            self.routing_limiter.leave(user_id)

    async def portfolio_snapshot(self, user_id):
        return await self._snapshot(user_id, None, 'portfolio')

    def _generation(self, user_id, scope):
        return self.market.session_generation(user_id) if scope in ('portfolio', 'risk') else None

    def _assert_generation(self, user_id, generation):
        if generation is not None:
            self.mcp.portfolio_service.assert_generation(user_id, generation)

    async def _snapshot(self, user_id, context, scope):
        started, run_id = time.monotonic(), str(uuid4())
        deadline = started + self.deadline_seconds
        with self.guard:
            if user_id in self.refresh_active or user_id in self.active or user_id in self.mcp.pending:
                raise HTTPException(409, 'An options request is already running.')
            if started - self.refresh_last.get(user_id, float('-inf')) < 5:
                raise HTTPException(429, 'Wait five seconds before refreshing again.')
            if len(self.refresh_active) + len(self.active) >= 4:
                raise HTTPException(429, 'Options monitoring is busy. Try again shortly.')
            self.refresh_active.add(user_id)
            self.refresh_last[user_id] = started
        detail, state = {'stages': ['mcp'], 'scope': scope, 'prompt_version': f'snapshot.{scope}.1'}, 'failed'
        try:
            async with asyncio.timeout_at(deadline):
                policy = await self._locked_worker(user_id, deadline, lambda check: self.risk_store.get_policy(user_id)) if scope == 'portfolio' else None
                generation = await self._locked_worker(user_id, deadline, lambda check: self._generation(user_id, scope))
                async with self.mcp.connection(user_id, context, run_id, **({"scope":scope, "risk_policy":policy, "session_generation":generation, "force_refresh":True, "deadline_monotonic":deadline} if scope == "portfolio" else {})) as connection:
                    result = await (self._portfolio_read(connection, detail) if scope == 'portfolio' else connection.snapshot())
                    if scope == 'portfolio':
                        result = self._risk_envelope(result)
                    await self._locked_worker(user_id, deadline, lambda check: self._assert_generation(user_id, generation))
                    detail.update({('evidence_id' if scope == 'portfolio' else 'snapshot_id'): result['evidence_id' if scope == 'portfolio' else 'snapshot_id'], 'tool_calls':1})
                detail['stages'].append('publication')
                def publish(check):
                    self._assert_generation(user_id, generation)
                    with self.store.connect() as db:
                        db.execute('BEGIN')
                        if scope == 'portfolio':
                            self.risk_store.save_report(db, user_id, self._risk_report(result))
                            detail['risk_report_id'] = result['risk_report']['report_id']
                            detail['risk_diagnostics'] = risk_diagnostics(self._risk_report(result), (time.monotonic() - started) * 1000)
                        self._record(user_id, run_id, 'snapshot', 'completed', started, detail, db=db)
                        self._assert_generation(user_id, generation)
                        check()
                await self._locked_worker(user_id, deadline, publish)
            state = 'completed'
            logger.info('options_run id=%s kind=snapshot status=completed duration_ms=%s', run_id, detail['duration_ms'])
            return result
        except RiskStoreBusyError:
            detail['failure_reason'] = 'risk_store_busy'
            raise HTTPException(503, 'Risk storage is busy. Retry shortly.', headers={'Retry-After':'1', 'X-Options-Run-Id':run_id}) from None
        except TimeoutError:
            state = 'timeout'
            raise HTTPException(504, 'Options snapshot timed out. Retry after the current broker request finishes.', headers={'X-Options-Run-Id': run_id}) from None
        except HTTPException as error:
            error.headers = {**(error.headers or {}), 'X-Options-Run-Id': run_id}
            raise
        except asyncio.CancelledError:
            state = 'cancelled'
            raise
        except Exception:
            raise HTTPException(503, 'The option chain could not be retrieved or validated. Check your Kotak connection and selection.', headers={'X-Options-Run-Id': run_id}) from None
        finally:
            try:
                await self._finish(user_id, run_id, 'snapshot', state, started, detail, deadline)
            finally:
                self._release(user_id, self.refresh_active)

    @staticmethod
    async def _portfolio_read(connection, detail):
        try:
            return await connection.portfolio_snapshot()
        finally:
            diagnostic = getattr(connection, 'risk_diagnostic', None)
            if diagnostic:
                detail['risk_diagnostics'] = dict(diagnostic)

    @staticmethod
    def _risk_envelope(value):
        from app.terminal.portfolio_risk_contracts import PortfolioRiskEnvelope
        return json.loads(PortfolioRiskEnvelope.model_validate_json(json.dumps(value, allow_nan=False)).model_dump_json())

    @staticmethod
    def _risk_report(value):
        from app.terminal.portfolio_risk_contracts import RiskReport
        return RiskReport.model_validate_json(json.dumps(value['risk_report'], allow_nan=False))

    def history(self, user_id, conversation_id):
        with self.store.connect() as db:
            owned = db.execute('SELECT context FROM option_chat_conversations WHERE id=? AND user_id=?',
                               (str(conversation_id), user_id)).fetchone()
            if not owned:
                raise HTTPException(404, 'Conversation not found.')
            rows = db.execute('SELECT message,answer,evidence,created_at FROM option_chat_turns WHERE conversation_id=? AND user_id=? ORDER BY id DESC LIMIT 20',
                              (str(conversation_id), user_id)).fetchall()
        context = json.loads(owned[0])
        evidence_key = 'risk_snapshot' if context.get('scope') == 'risk' else 'portfolio_snapshot' if context.get('scope') == 'portfolio' else 'snapshot'
        turns = []
        for message, answer, stored_evidence, created_at in reversed(rows):
            evidence = json.loads(stored_evidence)
            if context.get('scope') in REPORT_KINDS:
                evidence = load_report(self.store,user_id,context['scope'],evidence['report_id'])
                turns.append({'message':message,'answer':answer,'report':evidence,'created_at':created_at})
                continue
            # Old embedded-report and pre-risk evidence remain readable. Only
            # canonical references on new portfolio turns need owner-scoped hydration.
            if evidence_key in ('portfolio_snapshot', 'risk_snapshot') and 'risk_report_id' in evidence:
                report_id = evidence.pop('risk_report_id')
                report = self.risk_store.get_report(user_id, report_id)
                if report is None:
                    raise HTTPException(503, 'Historical risk evidence is unavailable.')
                evidence['risk_report'] = report.model_dump(mode='json')
            turns.append({'message': message, 'answer': answer, evidence_key: evidence, 'created_at': created_at})
        return {'conversation_id': str(conversation_id), 'context': context, 'turns': turns}

    async def chat(self, user_id, body, *, harness=None, parent_run_id=None):
        context = OptionsContext(underlying=body.underlying, exchange=body.exchange, expiry=body.expiry)
        return await self._run_specialist(user_id, body, specialist_scope('chain', context), context, harness=harness, parent_run_id=parent_run_id)

    async def portfolio_chat(self, user_id, body, *, harness=None, parent_run_id=None):
        return await self._run_specialist(user_id, body, specialist_scope('portfolio', None), None, harness=harness, parent_run_id=parent_run_id)

    async def portfolio_risk_chat(self, user_id, body, *, harness=None, parent_run_id=None):
        return await self._run_specialist(user_id, body, specialist_scope('risk', None), None, harness=harness, parent_run_id=parent_run_id)

    async def explain_report(self, user_id, body, *, harness=None, parent_run_id=None):
        return await self._run_specialist(user_id, body, report_scope(body.report_kind, body.report_id), None, harness=harness, parent_run_id=parent_run_id)

    async def _run_specialist(self, user_id, body, definition, context, *, harness=None, parent_run_id=None):
        active_harness = current_harness.get()
        inherited_harness = active_harness[0] if active_harness else None
        target_harness = harness or inherited_harness
        if target_harness is not None:
            with harness_context(target_harness, 'specialist'):
                return await self._chat(user_id, body, definition, context, harness=target_harness, parent_run_id=parent_run_id)
        created_harness = RequestHarness(auto=False,
            input_limit=self.config.agent_input_token_estimate_limit,
            context_limit=self.config.agent_context_token_limit)
        with harness_context(created_harness, 'specialist'):
            return await self._chat(user_id, body, definition, context, harness=created_harness, parent_run_id=parent_run_id)

    async def _chat(self, user_id, body, definition, context, selected_report=None, *, harness=None, parent_run_id=None):
        started = time.monotonic()
        active_harness = current_harness.get()
        inherited_harness = active_harness[0] if active_harness else None
        harness = harness or inherited_harness
        deadline = min(started + self.deadline_seconds, harness.deadline if harness else started + self.deadline_seconds)
        scope = definition.scope
        report_mode = scope in REPORT_KINDS
        if not self.status()['configured']:
            if not self.mcp.ready:
                raise HTTPException(503, 'Options monitoring is unavailable. The internal MCP service is not ready.')
            provider = provider_settings(self.config)
            raise HTTPException(503, provider.error or f'Options chat needs {provider.key_name} in the server configuration. Snapshot monitoring is still available.')
        with self.guard:
            stamp = time.monotonic()
            while self.recent and self.recent[0][0] < stamp - 60:
                self.recent.popleft()
            inherited_admission = harness is not None and harness.admission_owner == (self, user_id)
            if not inherited_admission and (user_id in self.active or user_id in self.refresh_active or user_id in self.mcp.pending):
                raise HTTPException(409, 'An options request is already running. Please wait.')
            if not inherited_admission and (sum(uid == user_id for _, uid in self.recent) >= 6 or len(self.active) + len(self.refresh_active) >= 4):
                raise HTTPException(429, 'Options chat is busy. Please wait a minute before retrying.')
            self.active.add(user_id)
            if not inherited_admission:
                self.recent.append((stamp, user_id))
        run_id, conversation_id = str(uuid4()), str(body.conversation_id or uuid4())
        effective_parent_run_id = parent_run_id or run_id
        detail, state = {'stages': [], 'scope': scope, 'prompt_version': definition.prompt_version,
                         'agent_id': definition.agent_id, 'parent_run_id': effective_parent_run_id}, 'failed'
        log_context = options_run.set(True)
        try:
            async with asyncio.timeout_at(deadline):
                if report_mode:
                    detail['stages'].append('selection')
                    # Admission and the same overall deadline cover selection;
                    # shielding retains cancelled synchronous storage capacity.
                    selected_report = await asyncio.shield(self._start_worker(user_id,
                        lambda: load_report(self.store, user_id, scope, body.report_id)))
                policy = await self._locked_worker(user_id, deadline, lambda check: self.risk_store.get_policy(user_id)) if scope in ('portfolio', 'risk') else None
                generation = await self._locked_worker(user_id, deadline, lambda check: self._generation(user_id, scope))
                def load_history(check):
                    history = self.history(user_id, body.conversation_id)
                    check()
                    self._assert_generation(user_id, generation)
                    return history
                history = await self._locked_worker(user_id, deadline, load_history) if body.conversation_id else None
                if history and history['context'] != definition.stored_context:
                    raise HTTPException(409, {'code': 'conversation_scope_changed', 'message': 'Start a new conversation after changing scope, specialist, or market selection.'})
                detail['stages'].append('mcp')
                mcp_scope = 'portfolio_analysis' if definition.allowed_tool == 'get_portfolio_analysis_snapshot' else scope
                connection_options = ({'scope': scope, 'selected_report': selected_report, 'deadline_monotonic': deadline} if report_mode else
                    {"scope": mcp_scope, "risk_policy": policy, "session_generation": generation, "deadline_monotonic": deadline} if scope in ('portfolio', 'risk') else
                    {"scope": scope, "deadline_monotonic": deadline})
                if harness:
                    connection_options['harness'] = harness
                async with self.mcp.connection(user_id, context, run_id, **connection_options) as connection:
                    try:
                        stage_started = time.monotonic()
                        snapshot = await connection._snapshot(definition.allowed_tool)
                        detail['mcp_ms'] = round((time.monotonic() - stage_started) * 1000)
                    finally:
                        diagnostic = getattr(connection, 'risk_diagnostic', None)
                        if diagnostic:
                            detail['risk_diagnostics'] = dict(diagnostic)
                    id_key = 'report_id' if report_mode else 'evidence_id' if scope in ('portfolio', 'risk') else 'snapshot_id'
                    detail[id_key] = snapshot[id_key]
                    if scope == 'portfolio':
                        detail.update(schema_version=snapshot.get('schema_version'),
                            data_quality={'completeness': snapshot.get('completeness'),
                                'section_states': {k: v.get('state') for k, v in snapshot.get('sections', {}).items()}})
                    previous = [{'user': t['message'], 'assistant': t['answer']} for t in (history or {}).get('turns', [])[-4:]]
                    if harness:
                        _, previous = bounded_context({'question': body.message, 'evidence': snapshot}, previous, input_limit=harness.input_limit)
                    def encode():
                        return json.dumps({'previous_conversation': previous, 'question': body.message,
                            ('current_report' if report_mode else 'current_risk_report' if scope == 'risk' else 'current_portfolio_snapshot' if scope == 'portfolio' else 'current_snapshot'): snapshot}, allow_nan=False)
                    prompt = encode()
                    while len(prompt.encode('utf-8')) > 65536 and previous:
                        previous.pop(0)
                        prompt = encode()
                    if len(prompt.encode('utf-8')) > 65536:
                        detail['failure_reason'] = 'context_limit'
                        raise HTTPException(503, 'Current evidence exceeds the safe input context limit.')
                    detail['stages'].append('model')
                    factory = get_agent(definition.agent_id)
                    agent = factory(self.config, snapshot, [connection.tools], scope=definition)
                    stage_started = time.monotonic()
                    try:
                        result = await agent.arun(prompt)
                    finally:
                        await close_agent_model(agent)
                        detail['model_ms'] = round((time.monotonic() - stage_started) * 1000)
                    await self._locked_worker(user_id, deadline, lambda check: self._assert_generation(user_id, generation))
                    detail['tool_calls'] = self.mcp.capabilities[connection.token].calls
                    if getattr(result, 'status', None) is not None and result.status.value != 'COMPLETED':
                        raise ValueError('Agent did not complete')
                    detail['stages'].append('output')
                    content = result.content
                    contract = definition.output_contract
                    answer = contract.model_validate_json(content) if isinstance(content, str) else contract.model_validate(content)
                    if not answer.answer.strip():
                        raise ValueError('Invalid answer: empty')
                    if report_mode:
                        if answer.report_ids != [snapshot['report_id']]:
                            raise ValueError('Invalid report ID citation')
                        if answer.evidence_ids != snapshot['evidence_ids']:
                            raise ValueError('Invalid report evidence citations')
                        references = answer.report_ids
                    elif scope == 'chain':
                        if answer.snapshot_ids != [snapshot['snapshot_id']]:
                            raise ValueError('Invalid snapshot ID citation')
                        references = answer.snapshot_ids
                    elif scope == 'portfolio':
                        if [str(x) for x in answer.evidence_ids] != [snapshot['evidence_id']]:
                            raise ValueError('Invalid portfolio evidence citation')
                        references = [str(x) for x in answer.evidence_ids]
                    elif scope == 'risk':
                        if [str(x) for x in answer.evidence_ids] != [snapshot['evidence_id']]:
                            raise ValueError('Invalid risk evidence citation')
                        if [str(x) for x in answer.risk_report_ids] != [snapshot['risk_report']['report_id']]:
                            raise ValueError('Invalid risk report citation')
                        references = [str(x) for x in answer.evidence_ids]
                    else:
                        raise ValueError(f'Unsupported scope: {scope}')
                    metrics = getattr(result, 'metrics', None)
                    detail['tokens'] = {k: getattr(metrics, k, None) for k in ('input_tokens', 'output_tokens', 'reasoning_tokens', 'total_tokens')}
                detail['stages'].append('publication')
                if harness:
                    detail['harness'] = harness.trace()
                def persist(check):
                    check()
                    self._assert_generation(user_id, generation)
                    created = datetime.now(UTC).isoformat()
                    with self.store.connect() as db:
                        db.execute(f'PRAGMA busy_timeout={max(1, int((deadline-time.monotonic())*1000))}')
                        check()
                        self._assert_generation(user_id, generation)
                        db.execute('BEGIN')
                        if scope == 'risk':
                            self.risk_store.save_report(db, user_id, self._risk_report(snapshot))
                        if not history:
                            db.execute('INSERT INTO option_chat_conversations VALUES (?,?,?,?)',
                                       (conversation_id, user_id, json.dumps(definition.stored_context), created))
                        stored_evidence = dict(snapshot)
                        if report_mode:
                            stored_evidence = {'report_id': snapshot['report_id']}
                        elif scope == 'risk':
                            stored_evidence.pop('risk_report')
                            stored_evidence['risk_report_id'] = snapshot['risk_report']['report_id']
                        db.execute('INSERT INTO option_chat_turns(conversation_id,user_id,message,answer,evidence,created_at) VALUES (?,?,?,?,?,?)',
                                   (conversation_id, user_id, body.message, answer.answer, json.dumps(stored_evidence, allow_nan=False), created))
                        check()
                        self._assert_generation(user_id, generation)
                        db.execute('INSERT INTO audit(user_id,created_at,event,detail) VALUES (?,?,?,?)',
                            (user_id, created, 'OPTIONS_CHAT_COMPLETED', json.dumps({'run_id': run_id, 'conversation_id': conversation_id,
                             id_key: snapshot[id_key], 'model': provider_settings(self.config).model, 'prompt_version': definition.prompt_version})))
                        check()
                        self._assert_generation(user_id, generation)
                        self._record(user_id, run_id, 'chat', 'completed', started, detail, db=db)
                        # Recheck after the final potentially blocking operation, before commit.
                        self._assert_generation(user_id, generation)
                        check()
                    return created
                created = await self._locked_worker(user_id, deadline, persist)
            state = 'completed'
            logger.info('options_run id=%s kind=chat status=completed duration_ms=%s', run_id, detail['duration_ms'])
            base_reply = {
                'conversation_id': conversation_id,
                'run_id': run_id,
                'parent_run_id': effective_parent_run_id,
                'agent_id': definition.agent_id,
                'answer': answer.answer,
                'created_at': created,
                'read_only': True,
            }
            if scope == 'risk':
                return {
                    **base_reply,
                    'evidence_ids': references,
                    'risk_report_ids': [str(x) for x in answer.risk_report_ids],
                    'risk_snapshot': snapshot,
                }
            elif scope == 'portfolio':
                return {
                    **base_reply,
                    'evidence_ids': references,
                    'portfolio_snapshot': snapshot,
                }
            elif report_mode:
                return {
                    **base_reply,
                    'report_ids': references,
                    'evidence_ids': answer.evidence_ids,
                    'report': snapshot,
                }
            else:  # chain
                return {
                    **base_reply,
                    'snapshot_ids': references,
                    'snapshot': snapshot,
                }
        except RiskStoreBusyError:
            detail['failure_reason'] = 'risk_store_busy'
            raise HTTPException(503, 'Risk storage is busy. Retry shortly.', headers={'Retry-After':'1', 'X-Options-Run-Id':run_id}) from None
        except TimeoutError:
            state = 'timeout'
            raise HTTPException(504, 'Options chat timed out. Retry after the current request finishes.', headers={'X-Options-Run-Id': run_id}) from None
        except HTTPException as error:
            error.headers = {**(error.headers or {}), 'X-Options-Run-Id': run_id}
            raise
        except asyncio.CancelledError:
            state = 'cancelled'
            raise
        except Exception as error:
            if isinstance(error, HarnessError):
                detail['failure_reason'], message = error.code, 'The request exceeded its safe execution budget.'
            else:
                detail['failure_reason'], message = provider_failure(self.config, error)
            raise HTTPException(503, message, headers={'X-Options-Run-Id': run_id}) from None
        finally:
            if harness:
                detail['harness'] = harness.trace()
            try:
                await self._finish(user_id, run_id, 'chat', state, started, detail, deadline)
            finally:
                if not inherited_admission:
                    self._release(user_id, self.active)
                options_run.reset(log_context)
