"""Authenticated source capture and private-to-specialist evidence projection.

All broker, SQLite and numeric work runs inside the bounded worker. Captured
results contain calculated evidence only, never raw portfolio/account envelopes.
"""
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from threading import Event
from contextlib import contextmanager

from app.brokers.base_broker import BrokerError
from .analytics_contracts import AnalyticsEvidence
from .analytics_engine import calculate_evidence
from .analytics_runtime import BoundedWork, TOOLS_BY_ROLE, TurnBudget
from .options_snapshot import OptionsContext, expiry_identity


@dataclass(frozen=True)
class CapturedAnalytics:
    owner_id: int
    session_generation: str
    context_json: str
    evidence_json: tuple[tuple[str,str], ...]

    def for_role(self,role):
        if role not in TOOLS_BY_ROLE:
            raise ValueError('Unknown specialist role')
        return {name:AnalyticsEvidence.model_validate_json(payload) for name,payload in self.evidence_json
                if name in TOOLS_BY_ROLE[role]}

    def binding(self):
        return dict(session_generation=self.session_generation,context=self.context_json,
                    evidence_ids={name:str(AnalyticsEvidence.model_validate_json(payload).evidence_id) for name,payload in self.evidence_json})


class AnalyticsCaptureService:
    def __init__(self,market,store,snapshots,portfolio_service,*,work=None):
        self.market,self.store,self.snapshots,self.portfolio = market,store,snapshots,portfolio_service
        self.work = work if work is not None else BoundedWork()

    async def capture(self,user_id,context,requested_tools,*,budget,historical_input=None):
        names = tuple(dict.fromkeys(requested_tools))
        known = set().union(*TOOLS_BY_ROLE.values())
        if type(user_id) is not int or user_id<=0 or not isinstance(context,OptionsContext) or not isinstance(budget,TurnBudget) or not names or not set(names)<=known:
            raise ValueError('Invalid authenticated analytics capture')
        # One shared deadline protects both the waiter and synchronous worker.
        deadline = min(budget.deadline,time.monotonic()+10)
        if deadline<=time.monotonic():
            raise ValueError('Turn deadline exhausted')
        copied = context.model_copy(deep=True)
        if historical_input is not None:
            from .analytics_inputs import HistoricalAnalyticsInput
            historical_input = HistoricalAnalyticsInput.model_validate(historical_input)
            if historical_input.context != copied:
                raise ValueError('Imported input market context differs')
        cancelled = Event()
        try:
            return await self.work.run(user_id,lambda:asyncio.to_thread(self._collect,user_id,copied,names,deadline,cancelled,historical_input),
                                       timeout=deadline-time.monotonic())
        except BaseException:
            cancelled.set()
            raise

    def _check(self,user_id,generation,deadline):
        if time.monotonic()>=deadline:
            raise TimeoutError('Analytics capture deadline exhausted')
        if self.portfolio is None:
            raise ValueError('Authenticated broker session required')
        self.portfolio.assert_generation(user_id,generation,deadline_monotonic=deadline)

    def _collect(self,user_id,context,names,deadline,cancelled,historical_input=None):
        def check(generation):
            if cancelled.is_set():
                raise TimeoutError('Analytics capture cancelled')
            self._check(user_id,generation,deadline)
            if self.market.session_generation(user_id)!=generation:
                raise ValueError('Broker session changed during capture')
        generation = self.market.session_generation(user_id)
        if not isinstance(generation,str) or not generation:
            raise ValueError('Authenticated broker session required')
        check(generation)
        inputs,refs,source_failure = {},[],None
        observed_at,coverage,limitations = None,{},[]
        imported = None
        if historical_input is not None:
            from .analytics_inputs import AnalyticsInputStore
            records = AnalyticsInputStore(self.store)
            saved = records.save(user_id,historical_input)
            inputs, reference, imported = records.load(user_id,saved['dataset_id'],context)
            refs.append(reference)
        if set(names)&TOOLS_BY_ROLE['options_trading_analysis']:
            try:
                chain = self.snapshots.fetch(user_id,context)
            except BrokerError:
                source_failure = 'UNAVAILABLE_BROKER_SOURCE'
            else:
                if chain.get('source')!='kotak' or chain.get('underlying')!=context.underlying or chain.get('exchange')!=context.exchange:
                    raise ValueError('Contradictory or synthetic market source')
                if context.expiry is not None and expiry_identity(chain.get('expiry'))!=expiry_identity(context.expiry):
                    raise ValueError('Contradictory market expiry')
                if not chain.get('snapshot_id'):
                    raise ValueError('Source evidence identity required')
                inputs['chain_rows'] = chain['rows']
                refs.append(str(chain['snapshot_id']))
                coverage['market_identity'] = {key:chain.get('identity_verification',{}).get(key) is True for key in ('underlying','exchange','expiry')}
                coverage['chain'] = 'returned_strikes_only'
                limitations.extend(str(value)[:1000] for value in chain.get('limitations',[])[:10])
                if chain.get('exchange_timestamp'):
                    observed_at = datetime.fromisoformat(chain['exchange_timestamp'])
        # Do not reconstruct Greeks, return history, margins or verified contract
        # identities from the chain's LTP-only rows. Their source adapters must
        # supply those inputs explicitly in a future capture extension.
        result = {}
        for name in names:
            check(generation)
            item = calculate_evidence(name,inputs,source_refs=tuple(refs),observed_at=observed_at)
            if imported is not None and name in ('get_technical_regime_snapshot','get_portfolio_attribution_and_rebalance','run_spot_vix_cvar_stress_matrix','get_vol_surface_and_greeks','get_nse_oi_microstructure'):
                item = item.model_copy(update={'observed_at':imported.observed_at,
                    'status':'PARTIAL' if item.status=='AVAILABLE' else item.status,
                    'coverage':{'input_provenance':'user_declared_unverified'},
                    'limitations':(*item.limitations,'Historical inputs and cash-flow adjustments are declared by the importing user, not independently verified.')})
            if source_failure:
                item = item.model_copy(update={'unavailable_reasons':{**item.unavailable_reasons,'broker_source':source_failure}})
            identity_unknown = coverage and not all(coverage['market_identity'].values())
            item = item.model_copy(update={'coverage':{**item.coverage,**coverage},'limitations':tuple(dict.fromkeys((*item.limitations,*limitations))),
                'status':'PARTIAL' if identity_unknown and item.status=='AVAILABLE' else item.status,
                'unavailable_reasons':{**item.unavailable_reasons,**({'market_identity':'provider_identity_unverified'} if identity_unknown else {})}})
            result[name] = item
        check(generation)
        if self.market.session_generation(user_id)!=generation:
            raise ValueError('Broker session changed during capture')
        @contextmanager
        def publication_guard():
            # Same market -> SQLite lock order as existing chat publication.
            remaining = max(0,deadline-time.monotonic())
            if not self.market.lock.acquire(timeout=remaining):
                raise TimeoutError('Capture publication lock deadline exhausted')
            try:
                yield
            finally:
                self.market.lock.release()
        self.store.capture_batch(user_id,result.values(),validate=lambda:check(generation),publication_guard=publication_guard,deadline=deadline)
        check(generation)
        return CapturedAnalytics(user_id,generation,context.model_dump_json(),
                                 tuple((name,item.model_dump_json()) for name,item in result.items()))
