"""Server-only evidence acquisition under the shared options request admission."""
import asyncio
from datetime import UTC,datetime
import time
from threading import Event
from fastapi import HTTPException
from .options_readiness import fetch_strategy_market_evidence
from .options_strategy_contracts import HoldingEvidence
from .options_strategies import analyze_strategy
from .portfolio_contracts import PortfolioSnapshot
from .options_platform_store import PlatformStoreBusyError,PlatformConflictError

class OptionsPlatformService:
    def __init__(self,agent,store): self.agent,self.store=agent,store

    async def _admitted(self,user_id,operation,*,background=False):
        """Share broker/global admission; cancelled worker retains its slot until done."""
        a=self.agent;started=time.monotonic();deadline=started+a.deadline_seconds
        with a.guard:
            if background and (a.active or a.mcp.pending or len(a.refresh_active)>=2):
                raise HTTPException(429,'Interactive options work has priority.')
            if user_id in a.refresh_active or user_id in a.active or user_id in a.mcp.pending:
                raise HTTPException(409,'An options request is already running.')
            if len(a.refresh_active)+len(a.active)>=4: raise HTTPException(429,'Options monitoring is busy.')
            if started-a.refresh_last.get(user_id,float('-inf'))<5: raise HTTPException(429,'Wait five seconds before refreshing again.')
            a.refresh_active.add(user_id);a.refresh_last[user_id]=started
        cancelled=Event()
        def check():
            if cancelled.is_set() or time.monotonic()>=deadline: raise TimeoutError()
        try:
            async with asyncio.timeout_at(deadline):
                # Broker functions perform their own bounded locks; never hold the market
                # lock across network work. _start_worker tracks cancellation survivors.
                worker=a._start_worker(user_id,lambda:operation(deadline,check))
                return await asyncio.shield(worker)
        except TimeoutError:
            raise HTTPException(504,'Options request timed out. Retry after the current broker request finishes.') from None
        finally:
            cancelled.set()
            a._release(user_id,a.refresh_active)

    async def market_snapshot(self,user_id,context):
        def acquire(deadline,check):
            check()
            a=self.agent;generation=a.market.session_generation(user_id)
            evidence=fetch_strategy_market_evidence(a.market,a.store,user_id,context,deadline=deadline)
            # Fence publication against a concurrent sign-in/sign-out.
            if not a.market.lock.acquire(timeout=max(0,deadline-time.monotonic())): raise TimeoutError()
            try:
                check()
                if a.market.session_generation(user_id)!=generation: raise ValueError('Session changed')
                return self.store.save_market_evidence(user_id,evidence,_check=check)
            finally: a.market.lock.release()
        try: return await self._admitted(user_id,acquire)
        except (HTTPException,asyncio.CancelledError,PlatformStoreBusyError,PlatformConflictError): raise
        except Exception:
            raise HTTPException(503,'Market evidence could not be retrieved or validated.') from None

    async def analyze(self,user_id,request):
        def calculate(deadline,check):
            check()
            evidence=self.store.get_market_evidence(user_id,request.evidence_id)
            if evidence is None: raise HTTPException(404,'Market evidence not found.')
            if request.mode=='hypothetical':
                report=analyze_strategy(request,evidence,None,datetime.now(UTC))
                check()
                return self.store.save_report(user_id,'analysis',report,_check=check)
            a=self.agent;service=a.mcp.portfolio_service;generation=a.market.session_generation(user_id)
            snapshot=service.fetch(user_id,expected_generation=generation,force=True,deadline_monotonic=deadline)
            holdings=self._holdings(snapshot,evidence)
            report=analyze_strategy(request,evidence,holdings,datetime.now(UTC))
            if not a.market.lock.acquire(timeout=max(0,deadline-time.monotonic())): raise TimeoutError()
            try:
                check()
                service.assert_generation(user_id,generation,deadline_monotonic=deadline)
                return self.store.save_report(user_id,'analysis',report,_check=check)
            finally: a.market.lock.release()
        try: return await self._admitted(user_id,calculate)
        except (HTTPException,asyncio.CancelledError,PlatformStoreBusyError,PlatformConflictError): raise
        except Exception:
            raise HTTPException(503,'Owned holding evidence could not be retrieved or validated.') from None

    @staticmethod
    def _holdings(snapshot,evidence):
        if not isinstance(snapshot,PortfolioSnapshot): snapshot=PortfolioSnapshot.model_validate(snapshot)
        section=snapshot.sections.get('holdings')
        if section is None or section.state!='available': return ()
        result=[]
        for row in section.rows:
            identifier=f'{row.exchange}|{row.token}' if row.exchange and row.token else None
            contract=next((x for x in evidence.contracts if x.instrument_id==identifier and x.kind=='equity'),None)
            if contract is None: continue
            result.append(HoldingEvidence(row_id=row.row_id,stock_contract_id=contract.instrument_id,
                underlying_id=row.underlying_key,available_quantity=row.available_quantity,
                acquisition_cost_per_share=row.average_price,observed_at=section.provider_timestamp or snapshot.source_observed_at,
                evidence_id=snapshot.evidence_id,identity_verified=row.identity_verified is True and row.currency=='INR',
                coverage_verified=row.inventory_coverage=='disjoint' and bool(row.inventory_coverage_basis)))
        return tuple(result)
