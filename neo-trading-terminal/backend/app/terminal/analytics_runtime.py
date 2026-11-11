"""Request-local budgets and cancellation-safe capacity accounting."""
import asyncio
import time
from dataclasses import dataclass, field

from .analytics_contracts import Role

TOOLS_BY_ROLE = {
    'options_trading_analysis': frozenset(('get_technical_regime_snapshot','get_vol_surface_and_greeks','get_nse_oi_microstructure')),
    'portfolio_analysis': frozenset(('get_participant_fii_dii_flow','compute_indian_statutory_costs_and_payoff','get_portfolio_attribution_and_rebalance')),
    'portfolio_risk': frozenset(('check_sebi_and_mwpl_compliance','run_spot_vix_cvar_stress_matrix')),
}


@dataclass
class TurnBudget:
    deadline: float = field(default_factory=lambda: time.monotonic()+30)
    calls: dict[str,int] = field(default_factory=dict)

    def consume(self, role: Role):
        if role not in TOOLS_BY_ROLE or time.monotonic() >= self.deadline or self.calls.get(role,0) >= 2:
            raise ValueError('Turn budget exhausted')
        self.calls[role] = self.calls.get(role,0)+1


class BoundedWork:
    def __init__(self, capacity=4):
        self.capacity = capacity
        self.pending = {}

    async def run(self, owner, factory, timeout=10):
        if owner in self.pending or len(self.pending) >= self.capacity:
            raise ValueError('Analytics capacity exhausted')
        task = asyncio.create_task(factory())
        self.pending[owner] = task
        def finished(done):
            if self.pending.get(owner) is done:
                self.pending.pop(owner,None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        async with asyncio.timeout(timeout):
            return await asyncio.shield(task)
