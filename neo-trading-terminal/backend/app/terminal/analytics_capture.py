"""Authenticated source capture and private-to-specialist evidence projection.

All broker, SQLite and numeric work runs inside the bounded worker. Captured
results contain calculated evidence only, never raw portfolio/account envelopes.
"""
import asyncio
import time
from dataclasses import dataclass,field
from datetime import datetime, UTC
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
    input_dataset_id: str | None = field(default=None,repr=False)

    def for_role(self,role):
        if role not in TOOLS_BY_ROLE:
            raise ValueError('Unknown specialist role')
        return {name:AnalyticsEvidence.model_validate_json(payload) for name,payload in self.evidence_json
                if name in TOOLS_BY_ROLE[role]}

    def binding(self):
        return dict(session_generation=self.session_generation,context=self.context_json,
                    evidence_ids={name:str(AnalyticsEvidence.model_validate_json(payload).evidence_id) for name,payload in self.evidence_json})


class AnalyticsCaptureService:
    def __init__(self,market,store,snapshots,portfolio_service,*,work=None,catalogue=None,risk_policy_reader=None,advisory_enabled=False):
        self.market,self.store,self.snapshots,self.portfolio = market,store,snapshots,portfolio_service
        self.work = work if work is not None else BoundedWork()
        self.catalogue = catalogue
        self.risk_policy_reader = risk_policy_reader
        self.advisory_enabled = advisory_enabled is True

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
        captured_policy_revision = None
        def check(generation):
            if cancelled.is_set():
                raise TimeoutError('Analytics capture cancelled')
            self._check(user_id,generation,deadline)
            if self.market.session_generation(user_id)!=generation:
                raise ValueError('Broker session changed during capture')
            if captured_policy_revision is not None and self.risk_policy_reader(user_id).revision!=captured_policy_revision:
                raise ValueError('Risk policy changed during capture')
        generation = self.market.session_generation(user_id)
        if not isinstance(generation,str) or not generation:
            raise ValueError('Authenticated broker session required')
        check(generation)
        inputs,refs,source_failure = {},[],None
        observed_at,coverage,limitations = None,{},[]
        imported = None
        input_dataset_id = None
        account_report = None
        account_reason = None
        participant_reason = None
        ban_publication, ban_reason = None, None
        account_refs = ()
        quote_depth = None
        depth_reason = None
        candidate_contracts = []
        history_source = None
        history_reason = None
        imported_tools = set()
        candidate_tool = next((name for name in names if name in ('get_nse_oi_microstructure','get_vol_surface_and_greeks')),None)
        if historical_input is not None:
            from .analytics_inputs import AnalyticsInputStore
            records = AnalyticsInputStore(self.store)
            saved = records.save(user_id,historical_input)
            input_dataset_id = saved['dataset_id']
            inputs, reference, imported = records.load(user_id,saved['dataset_id'],context)
            for tool,keys in {
                'get_technical_regime_snapshot':('bars',),'get_vol_surface_and_greeks':('surface_rows',),
                'get_nse_oi_microstructure':('gex_rows','cash_future_basis'),'get_portfolio_attribution_and_rebalance':('verified_returns','declared_attribution'),
                'run_spot_vix_cvar_stress_matrix':('risk_positions',),'check_sebi_and_mwpl_compliance':('rules',),
                'compute_indian_statutory_costs_and_payoff':('fee_transactions',),
            }.items():
                if any(key in inputs for key in keys):
                    imported_tools.add(tool)
            refs.append(reference)
            request = inputs.pop('participant_report_request',None)
            if request is not None and 'get_participant_fii_dii_flow' in names:
                from .analytics_sources import ParticipantReports
                reports = ParticipantReports(self.store)
                if request['csv'] is not None:
                    inputs['participant_report'] = reports.parse_report(request['date'],request['csv'])
                else:
                    import httpx
                    try:
                        inputs['participant_report'] = reports.fetch(request['date'],deadline=deadline)
                    except (httpx.HTTPError,ValueError):
                        check(generation)
                        participant_reason='official_participant_source_unavailable_or_invalid'
                if request['csv'] is not None:
                    imported_tools.add('get_participant_fii_dii_flow')
                history_request = inputs.pop('participant_history_request',{})
                if history_request.get('reports') and inputs.get('participant_report') is not None:
                    imported_tools.add('get_participant_fii_dii_flow')
                    from .nse_participant_flow import participant_history_change
                    history = [reports.parse_report(row['report_date'],row['csv']) for row in history_request['reports']]
                    refs.extend('nse-participant-oi:'+row['report_date']+':'+row['checksum'] for row in history)
                    inputs['participant_report'].update(participant_history_change(inputs['participant_report'],history,
                        sessions_complete=history_request['sessions_complete'],price_return=history_request['price_return']))
                if inputs.get('participant_report') is not None:
                    refs.append('nse-participant-oi:'+request['date'].isoformat()+':'+inputs['participant_report']['checksum'])
        if self.risk_policy_reader is not None and set(names)&TOOLS_BY_ROLE['portfolio_risk']:
            from .portfolio_risk import evaluate_portfolio_risk
            policy = self.risk_policy_reader(user_id)
            captured_policy_revision = policy.revision
            check(generation)
            try:
                private_snapshot = self.portfolio.fetch(user_id,expected_generation=generation,deadline_monotonic=deadline)
            except BrokerError:
                # A fast account-source failure need not discard independent
                # evidence. Expired sessions, policies and deadlines still fail.
                check(generation)
                account_reason = 'broker_account_source_unavailable'
            else:
                check(generation)
                account_report = evaluate_portfolio_risk(private_snapshot,policy,datetime.now(UTC)).model_dump(mode='json')
                account_refs = (str(private_snapshot.evidence_id),account_report['report_id'])
            if self.risk_policy_reader(user_id).revision!=policy.revision:
                raise ValueError('Risk policy changed during account capture')
        if self.catalogue is not None and 'get_technical_regime_snapshot' in names and inputs.get('bars') is None:
            from .analytics_history import technical_history,HistorySourceUnavailable
            try:
                history_source = technical_history(self.market,self.catalogue,user_id,context,deadline,lambda:check(generation))
            except (BrokerError,HistorySourceUnavailable):
                history_reason = 'broker_daily_history_invalid_or_unavailable'
            if history_source is not None:
                inputs['bars'] = history_source['bars']
                refs.append(history_source['source_reference'])
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
                if self.catalogue is not None and set(names)&{'get_nse_oi_microstructure','get_vol_surface_and_greeks'}:
                    if context.exchange!='nse_fo':
                        depth_reason = 'quote_depth_adapter_supports_nse_only'
                    else:
                        from .options_readiness import legacy_chain_to_evidence,quotes_to_evidence
                        check(generation)
                        catalogue = self.catalogue.search(query=context.underlying,exchange='nse_fo',kind='OPTION',limit=5000)['items']
                        from .analytics_identity import eligible_contracts
                        eligible_contracts(chain,catalogue,[])  # Reject explicit identity contradictions before quote acquisition.
                        matched = tuple(contract for contract in legacy_chain_to_evidence(chain,catalogue=catalogue).contracts
                                        if contract.instrument_id.startswith('nse_fo|'))
                        if not matched or len(matched)>50:
                            depth_reason = 'no_unambiguous_bounded_catalogue_quote_batch'
                        else:
                            check(generation)
                            try:
                                rows = self.market.call('quotes',user_id=user_id,quote_type='all',deadline_monotonic=deadline,
                                    instrument_tokens=[{'exchange_segment':'nse_fo','instrument_token':contract.instrument_id.split('|',1)[1]} for contract in matched])
                            except BrokerError:
                                depth_reason = 'broker_quote_depth_unavailable'
                            else:
                                check(generation)
                                depth = quotes_to_evidence(rows,matched,datetime.now(UTC))
                                quote_depth = depth.model_dump(mode='json')
                                candidate_contracts = eligible_contracts(chain,catalogue,quote_depth['quotes'])
                                reported_pairs = sum(quote.bid is not None and quote.ask is not None for quote in depth.quotes)
                                if not reported_pairs:
                                    depth_reason = 'broker_returned_no_bid_ask_pairs'
                                refs.append(str(depth.evidence_id))
                                coverage['quote_depth'] = dict(scope='catalogue_matched_contracts_only',requested=len(matched),returned=len(depth.quotes),
                                    reported_bid_ask_pairs=reported_pairs,exchange_timestamp_verified=False,underlying_identity_verified=False)
                                limitations.extend(depth.limitations)
        # Do not reconstruct Greeks, return history, margins or verified contract
        # identities from the chain's LTP-only rows. Their source adapters must
        # supply those inputs explicitly in a future capture extension.
        if self.catalogue is not None and 'check_sebi_and_mwpl_compliance' in names:
            import httpx
            from zoneinfo import ZoneInfo
            from .analytics_ban_source import fetch_ban_publication
            check(generation)
            try:
                ban_publication = fetch_ban_publication(datetime.now(UTC).astimezone(ZoneInfo('Asia/Kolkata')).date(),deadline=deadline)
            except (httpx.HTTPError,ValueError):
                ban_reason = 'official_dated_ban_publication_unavailable'
            check(generation)
        result = {}
        for name in names:
            check(generation)
            item_refs = (*refs,*account_refs) if name in TOOLS_BY_ROLE['portfolio_risk'] else tuple(refs)
            item = calculate_evidence(name,inputs,source_refs=item_refs,observed_at=observed_at)
            if name == 'check_sebi_and_mwpl_compliance':
                if ban_publication is not None:
                    item = item.model_copy(update={'metrics':{**item.metrics,'official_ban_publication':ban_publication},
                        'status':'PARTIAL','source_refs':(*item.source_refs,ban_publication['source']+'#sha256='+ban_publication['checksum']),
                        'limitations':(*item.limitations,'Published symbol list only; contract mapping, complete account exposure and intraday monitoring remain unverified.')})
                elif ban_reason is not None:
                    item = item.model_copy(update={'unavailable_reasons':{**item.unavailable_reasons,'official_ban_publication':ban_reason}})
            if name=='get_participant_fii_dii_flow' and participant_reason is not None:
                item=item.model_copy(update={'unavailable_reasons':{**item.unavailable_reasons,'participant_report':participant_reason}})
            if name=='get_technical_regime_snapshot' and history_source is not None:
                item = item.model_copy(update={'observed_at':history_source['last_observation'],
                    'coverage':{**item.coverage,'source_semantics':'historical_closed_bars','history_basis':'documented_broker_candles_adjustments_unverified'},
                    'limitations':(*item.limitations,*history_source['limitations'])})
            if name=='get_technical_regime_snapshot' and history_reason is not None:
                item = item.model_copy(update={'unavailable_reasons':{**item.unavailable_reasons,'bars':history_reason}})
            if account_report is not None and name in TOOLS_BY_ROLE['portfolio_risk']:
                item = item.model_copy(update={'metrics':{**item.metrics,'existing_account_risk_report':account_report},
                    'status':'PARTIAL','coverage':{**item.coverage,'account_risk_basis':'existing_account_only_not_combined_with_proposal'},
                    'limitations':(*item.limitations,'Existing-account report is derived separately; it is not a combined-account post-proposal assessment.')})
            if account_reason is not None and name in TOOLS_BY_ROLE['portfolio_risk']:
                item = item.model_copy(update={'unavailable_reasons':{**item.unavailable_reasons,'existing_account_risk_report':account_reason}})
            if name in ('get_nse_oi_microstructure','get_vol_surface_and_greeks'):
                if quote_depth is not None:
                    item = item.model_copy(update={'metrics':{**item.metrics,'broker_quote_depth':quote_depth},
                        'status':'PARTIAL' if reported_pairs or item.status=='AVAILABLE' else item.status})
                    if self.advisory_enabled and candidate_contracts and name==candidate_tool:
                        from .quant_proposals import candidate_proposals,spread_payoff
                        identity = item.evidence_id
                        quotes = {quote['contract_id']:quote for quote in quote_depth['quotes']}
                        proposals = []
                        for proposal in candidate_proposals(candidate_contracts,identity,datetime.now(UTC)):
                            try:
                                spread_payoff(proposal,quotes)
                            except ValueError:
                                continue
                            proposals.append(proposal)
                        item = item.model_copy(update={'candidate_proposals':tuple(proposals),
                            'coverage':{**item.coverage,'proposal_identity_basis':'documented_provider_neosymbol_and_underlying_code_cross_checked_against_raw_master_and_common_lot'},
                            'limitations':(*item.limitations,'Proposal identity uses explicit broker underlying codes; cash-token/settlement/exchange-time verification is not established. Displayed depth is not a fill guarantee.')})
                if depth_reason is not None:
                    item = item.model_copy(update={'unavailable_reasons':{**item.unavailable_reasons,'quote_depth':depth_reason},
                        'status':'PARTIAL' if item.status=='AVAILABLE' else item.status})
            if imported is not None and name in imported_tools:
                item = item.model_copy(update={'observed_at':imported.observed_at,
                    'status':'PARTIAL' if item.status=='AVAILABLE' else item.status,
                    'coverage':{**item.coverage,'input_provenance':'user_declared_unverified'},
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
                                 tuple((name,item.model_dump_json()) for name,item in result.items()),input_dataset_id)
