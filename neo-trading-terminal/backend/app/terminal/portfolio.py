"""Legacy website portfolio adapter over shared session observations."""
from .portfolio_service import PortfolioSnapshotService
from .portfolio_normalization import to_legacy_portfolio


def snapshot(market, store, user_id, force=False):
    service = PortfolioSnapshotService(market, store)
    return to_legacy_portfolio(service.fetch(user_id, expected_generation=market.session_generation(user_id), force=force))
