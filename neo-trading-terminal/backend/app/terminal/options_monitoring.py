"""Opt-in durable monitor; read-only broker acquisition shares interactive admission."""
import asyncio
from datetime import UTC,datetime
from decimal import Decimal,localcontext
import json
import time
from threading import Event
from zoneinfo import ZoneInfo
from .options_market_contracts import MarketDecimal
from pydantic import TypeAdapter
from .options_strategy_contracts import calculation_context
from .options_platform_risk import evaluate_platform_risk
from .options_lot_ledger import assess_lot_ledger

TRADE_MAPPING_VERSION='kotak-trade-report.documented.v1'
TRADE_MAPPING_SOURCE='https://github.com/Kotak-Neo/Kotak-neo-api-v2/blob/main/docs/Trade_report.md'

def normalize_trade_report(raw):
    """Only documented full fill records; never resolve empty tok by symbol.

    No brokerage/cost evidence is supplied by this schema. Unknown shapes remain
    unavailable. Trade reports cover the current trading day, not full history.
    """
    unavailable=dict(version=TRADE_MAPPING_VERSION,status='unavailable',fills=[],limitations=['Trade report is day-scoped; fees and historical coverage unavailable.'],source_reference=TRADE_MAPPING_SOURCE)
    if not isinstance(raw,dict) or raw.get('stat') not in ('ok','Ok') or raw.get('stCode')!=200 or not isinstance(raw.get('data'),list): return unavailable
    if len(raw['data'])>1000: return unavailable
    try:
        if len(json.dumps(raw).encode())>1048576: return unavailable
    except (ValueError,TypeError,RecursionError): return unavailable
    fills=[];seen=set()
    for row in raw['data']:
        try:
            if not isinstance(row,dict) or row.get('rptTp')!='fill': continue
            fid=row['flId'];token=row['tok'];exchange=row['exSeg'];side=row['trnsTp']
            if not isinstance(fid,str) or not fid or len(fid)>100 or not isinstance(token,str) or not token or len(token)>100 or exchange not in ('nse_cm','nse_fo') or side not in ('B','S'): continue
            identity=f'{exchange}|{fid}'
            if identity in seen: return unavailable
            quantity=TypeAdapter(MarketDecimal).validate_python(row['fldQty'])
            price=TypeAdapter(MarketDecimal).validate_python(row['avgPrc'])
            if quantity<=0 or quantity!=quantity.to_integral_value(): continue
            timestamp=datetime.strptime(row['exTm'],'%d-%b-%Y %H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Kolkata'))
            seen.add(identity)
            fills.append(dict(fill_id=identity,contract_id=f'{exchange}|{token}',quantity=str(quantity),price=str(price),side='BUY' if side=='B' else 'SELL',executed_at=timestamp.isoformat(),costs_inr=None,source='broker_trade_report',mapping_version=TRADE_MAPPING_VERSION))
        except (KeyError,ValueError,TypeError): continue
    return dict(unavailable,status='available' if fills or not raw['data'] else 'unavailable',fills=fills)

def association_pnl(report,rows,fills,*,costs_inr=None):
    """Comparison only: day-scope fills/net inventory cannot prove remaining lots."""
    with localcontext(calculation_context()):
        ids=[report.request.stock_contract_id,report.request.call_contract_id]+([report.request.put_contract_id] if report.request.put_contract_id else [])
        by_id={f'{r.exchange}|{r.token}':r for r in rows}
        unavailable=dict(status='cannot_assess',reason='compatible exact inventory and fills required',realized_inr=None,unrealized_inr=None,yield_fraction=None)
        if len(by_id)!=len(rows) or set(by_id)!=set(ids): return unavailable
        if any(not r.identity_verified or r.currency!='INR' or r.inventory_coverage!='disjoint' or not r.inventory_coverage_basis for r in rows): return unavailable
        if any(f['contract_id'] not in ids for f in fills): return unavailable
        gross=Decimal(0);basis=Decimal(0)
        for index,id in enumerate(ids):
            leg=[f for f in fills if f['contract_id']==id]
            side='SELL' if index==1 else 'BUY'
            if not leg or any(f['side']!=side for f in leg): return dict(status='cannot_assess',reason='opening fill direction or coverage unknown',realized_inr=None,unrealized_inr=None,yield_fraction=None)
            quantity=sum((Decimal(f['quantity']) for f in leg),Decimal(0))
            row=by_id.get(id)
            expected=report.quantity*(-1 if side=='SELL' else 1)
            if quantity!=report.quantity or row is None or row.quantity!=expected or row.last_price is None: return dict(status='cannot_assess',reason='exact marked inventory coverage unavailable',realized_inr=None,unrealized_inr=None,yield_fraction=None)
            paid=sum((Decimal(f['quantity'])*Decimal(f['price']) for f in leg),Decimal(0))
            sign=-1 if side=='SELL' else 1
            gross+=sign*(quantity*row.last_price-paid);basis+=sign*paid
        return dict(status='cannot_assess',reason='remaining-lot allocation unavailable; selected fills may have been closed or replaced',
            comparison_label='mark_versus_selected_fills_not_actual_pnl',comparison_inr=str(gross),
            comparison_after_declared_costs_inr=str(gross-costs_inr) if costs_inr is not None else None,
            costs_source='user_declared',realized_inr=None,unrealized_inr=None,yield_fraction=None,
            fill_capital_inr=str(basis),baseline_capital_deviation_inr=str(basis-report.current_capital) if report.current_capital is not None else None)

class OptionsMonitoringService:
    def __init__(self,platform,*,clock=time.time):
        self.platform=platform;self.store=platform.store;self.agent=platform.agent;self.clock=clock
        self.task=None;self.ticks={};self.running=False

    async def start(self):
        if self.task is None:
            self.running=True;self.task=asyncio.create_task(self._loop())

    async def stop(self):
        self.running=False
        if self.task:
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True);self.task=None
        for task in tuple(self.ticks.values()): task.cancel()
        if self.ticks: await asyncio.gather(*tuple(self.ticks.values()),return_exceptions=True)

    def _session(self,owner):
        sess=self.agent.market.get_session(owner)
        return sess.generation if sess.source=='kotak' and sess.broker.is_authenticated else None

    async def _loop(self):
        while self.running:
            try: await self.run_due()
            except asyncio.CancelledError: raise
            except Exception: pass # private provider failures never enter logs
            await asyncio.sleep(1)

    async def run_due(self):
        owners=await asyncio.to_thread(self.store.monitor_owners)
        for owner in owners:
            # Actual worker ownership wins over expired durable leases.
            with self.agent.guard:
                busy=owner in self.agent.refresh_active or owner in self.agent.active or bool(self.agent.workers.get(owner)) or owner in self.agent.mcp.pending
                priority=bool(self.agent.active or self.agent.mcp.pending) or len(self.agent.refresh_active)>=2
            if busy or priority or owner in self.ticks: continue
            generation=self._session(owner)
            now=self.clock()
            if generation is None:
                settings=await asyncio.to_thread(self.store.get_monitoring,owner)
                if settings.get('generation'):
                    claim=await asyncio.to_thread(self.store.claim_monitor_unavailable,owner,settings['generation'],now=now)
                    if claim: await self._publish_unavailable(owner,claim,'session_unavailable')
                await asyncio.to_thread(self.store.suspend_monitor,owner,now=now);continue
            await asyncio.to_thread(self.store.resume_monitor,owner,generation,now=now)
            claim=await asyncio.to_thread(self.store.claim_monitor,owner,generation,now=now)
            if claim:
                task=asyncio.create_task(self._tick(owner,claim));self.ticks[owner]=task
                task.add_done_callback(lambda done,uid=owner:self.ticks.pop(uid,None))

    def _fetch(self,owner,generation,deadline,check):
        a=self.agent;service=a.mcp.portfolio_service
        snapshot=service.fetch(owner,expected_generation=generation,force=True,deadline_monotonic=deadline)
        check();service.assert_generation(owner,generation,deadline_monotonic=deadline)
        return snapshot

    async def acquire_association_evidence(self,owner):
        def operation(deadline,check):
            generation=self._session(owner)
            if generation is None: raise ValueError('Broker session required')
            snapshot=self._fetch(owner,generation,deadline,check)
            try: raw=self.agent.market.call('trade_report',user_id=owner,deadline_monotonic=deadline)
            except Exception: raw=None
            check()
            fills=normalize_trade_report(raw)
            service=self.agent.mcp.portfolio_service
            service._acquire(self.agent.market.lock,deadline)
            try:
                check();service.assert_generation(owner,generation,deadline_monotonic=deadline)
                return self.store.save_private_record(owner,'portfolio',dict(snapshot=snapshot.model_dump(mode='json'),fills=fills,generation=generation),now=self.clock(),_check=check)
            finally: self.agent.market.lock.release()
        return await self.platform._admitted(owner,operation)

    def associate(self,owner,baseline_id,body):
        from .portfolio_contracts import PortfolioSnapshot
        baseline=self.store.get_baseline(owner,baseline_id)
        if baseline is None: raise KeyError('Baseline not found')
        report=self.store.get_report(owner,'analysis',baseline.analysis_id)
        records=self.store.list_private_records(owner,'portfolio',limit=100)
        record=next((r for r in records if r['snapshot']['evidence_id']==str(body.portfolio_evidence_id)),None)
        if record is None: raise ValueError('Owned server portfolio evidence required')
        if self._session(owner)!=record['generation']: raise ValueError('Evidence session changed')
        snapshot=PortfolioSnapshot.model_validate(record['snapshot'])
        rows=[row for sec in snapshot.sections.values() if sec.state=='available' for row in sec.rows if row.row_id in body.row_ids]
        if len(rows)!=len(set(body.row_ids)) or len(set(body.row_ids))!=len(body.row_ids): raise ValueError('Exact selectable rows required')
        ids=[report.request.stock_contract_id,report.request.call_contract_id]+([report.request.put_contract_id] if report.request.put_contract_id else [])
        canonical={f'{r.exchange}|{r.token}':r for r in rows}
        if len(canonical)!=len(rows) or set(canonical)!=set(ids): raise ValueError('Exact leg identity association required')
        for index,id in enumerate(ids):
            row=canonical[id]
            if not row.identity_verified or row.currency!='INR' or row.inventory_coverage!='disjoint' or not row.inventory_coverage_basis or row.quantity!=report.quantity*(-1 if index==1 else 1): raise ValueError('Verified compatible quantity required')
        ledger=None
        if body.lot_ledger_id is not None:
            saved=self.store.get_private_record(owner,'lot_ledger',body.lot_ledger_id)
            if saved is None: raise ValueError('Owned user-declared lot ledger required')
            ledger={key:value for key,value in saved.items() if key!='id'}
            if body.costs_inr is not None: raise ValueError('Ledger trade costs are authoritative; separate costs would be ambiguous')
        fill_source=ledger['trades'] if ledger is not None else record['fills']['fills']
        selected=[f for f in fill_source if f['fill_id'] in body.fill_ids]
        if len(selected)!=len(set(body.fill_ids)) or len(set(body.fill_ids))!=len(body.fill_ids): raise ValueError('Exact server fill references required')
        executed=False
        if body.confirm_executed:
            for index,id in enumerate(ids):
                fs=[f for f in selected if f['contract_id']==id]
                if not fs or any(f['side']!=('SELL' if index==1 else 'BUY') for f in fs) or sum((Decimal(f['quantity']) for f in fs),Decimal(0))!=report.quantity: raise ValueError('Complete verified opening fills required')
            if any(f['contract_id'] not in ids for f in selected): raise ValueError('Unrelated fill')
            # Documented day-scoped fills prove trades occurred, not which lots
            # remain. No canonical remaining-lot allocation source is supported.
            executed=False
        pnl=assess_lot_ledger(report,rows,body.fill_ids,ledger,snapshot_observed_at=snapshot.source_observed_at) if ledger is not None and body.confirm_executed else association_pnl(report,rows,selected,costs_inr=body.costs_inr)
        executed=body.confirm_executed and pnl.get('execution_confirmed') is True
        payload=dict(association_id=str(__import__('uuid').uuid4()),baseline_id=str(baseline.baseline_id),baseline_analysis_id=str(report.report_id),portfolio_evidence_id=str(snapshot.evidence_id),row_ids=list(body.row_ids),fill_ids=list(body.fill_ids),revision_id=str(__import__('uuid').uuid4()),executed_confirmed=executed,baseline_mode=report.request.mode,
            lot_ledger_id=str(body.lot_ledger_id) if body.lot_ledger_id is not None else None,execution_source='user_declared' if executed else None,current_coverage_verified=pnl.get('current_coverage_verified',False),
            execution_confirmation_requested=body.confirm_executed,execution_confirmation_status='confirmed_user_declared' if executed else 'cannot_assess',execution_confirmation_reason=pnl['reason'],
            costs_inr=None if body.costs_inr is None else str(body.costs_inr),costs_source=body.costs_source,contract_ids=ids,
            pnl=pnl,created_at=datetime.now(UTC).isoformat())
        # Association selection is a threadpool operation; bound its final lock
        # wait and hold the same session lock as sign-in/out through publication.
        if not self.agent.market.lock.acquire(timeout=1):
            from .options_platform_store import PlatformStoreBusyError
            raise PlatformStoreBusyError('Session publication busy')
        try:
            if self._session(owner)!=record['generation']: raise ValueError('Evidence session changed')
            return self.store.save_private_record(owner,'association',payload,now=self.clock())
        finally: self.agent.market.lock.release()

    async def _tick(self,owner,claim):
        def operation(deadline,check):
            snapshot=self._fetch(owner,claim['generation'],deadline,check)
            associations=self.store.list_private_records(owner,'association',limit=100)
            reports=self.store.list_reports(owner,'analysis',limit=100)
            # History is immutable; only the latest revision of each baseline is
            # active. Re-assess marks against this cycle, never saved old P&L.
            current=[];seen=set();report_by_id={str(r.report_id):r for r in reports}
            records=self.store.list_private_records(owner,'portfolio',limit=100)
            for association in associations:
                key=association['baseline_id']
                if key in seen: continue
                seen.add(key)
                original=next((r for r in records if r['snapshot']['evidence_id']==association['portfolio_evidence_id']),None)
                report=report_by_id.get(association['baseline_analysis_id'])
                rows=[r for sec in snapshot.sections.values() if sec.state=='available' for r in sec.rows if f'{r.exchange}|{r.token}' in association['contract_ids']]
                fills=[f for f in original['fills']['fills'] if f['fill_id'] in association['fill_ids']] if original else []
                pnl=dict(status='cannot_assess',reason='current compatible execution evidence unavailable',realized_inr=None,unrealized_inr=None,yield_fraction=None)
                if report and original and original['generation']==claim['generation']:
                    saved=self.store.get_private_record(owner,'lot_ledger',association['lot_ledger_id']) if association.get('lot_ledger_id') else None
                    if saved is not None and association['executed_confirmed']:
                        pnl=assess_lot_ledger(report,rows,association['fill_ids'],{key:value for key,value in saved.items() if key!='id'},snapshot_observed_at=snapshot.source_observed_at)
                    else:
                        pnl=association_pnl(report,rows,fills,costs_inr=Decimal(association['costs_inr']) if association.get('costs_inr') is not None else None)
                current.append(dict(association,pnl=pnl,current_coverage_verified=pnl.get('current_coverage_verified',False),current_portfolio_evidence_id=str(snapshot.evidence_id)))
            associations=current
            equity=self.store.list_private_records(owner,'equity',limit=1)
            from .options_platform_risk import EquityObservation
            observations=tuple(EquityObservation.model_validate(x) for x in equity[0]['observations']) if equity else ()
            report=evaluate_platform_risk(self.store.get_risk_policy(owner),snapshot,reports,associations,observations,as_of=datetime.fromtimestamp(self.clock(),UTC))
            report['associations']=associations
            states={c['key']:c['outcome'] if c['limit'] is not None else 'disabled' for c in report['checks']}
            states.update({'association:'+a['baseline_id']:('pass' if a['pnl']['status']=='assessed' else 'cannot_assess') for a in associations})
            service=self.agent.mcp.portfolio_service;service._acquire(self.agent.market.lock,deadline)
            try:
                check();service.assert_generation(owner,claim['generation'],deadline_monotonic=deadline)
                return self.store.finish_monitor(owner,claim,states,now=self.clock(),report=report,_check=check)
            finally: self.agent.market.lock.release()
        try: await self.platform._admitted(owner,operation,background=True)
        except asyncio.CancelledError: raise
        except Exception:
            await self._publish_unavailable(owner,claim,'acquisition_unavailable')
            if self._session(owner)!=claim['generation']:
                await asyncio.to_thread(self.store.suspend_monitor,owner,now=self.clock())

    async def _publish_unavailable(self,owner,claim,reason):
        """Publish only a data-quality assessment; never reuse broker evidence.

        This orchestration is separate from the shielded failed/timed-out broker
        worker. Its cancellation flag fences the storage transaction while actual
        broker admission stays owned until that worker exits.
        """
        cancelled=Event()
        def check():
            if cancelled.is_set(): raise TimeoutError('Unavailable publication cancelled')
        worker=asyncio.create_task(asyncio.to_thread(self.store.finish_monitor_unavailable,owner,claim,
            now=self.clock(),reason=reason,_check=check))
        try: return await asyncio.shield(worker)
        finally:
            cancelled.set()
            # Consume a late cancellation-fenced worker exception.
            worker.add_done_callback(lambda task:task.exception() if not task.cancelled() else None)
