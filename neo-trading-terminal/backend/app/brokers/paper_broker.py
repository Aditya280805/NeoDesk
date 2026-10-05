from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import uuid4

from app.brokers.base_broker import BrokerError, BrokerInterface


class PaperBroker(BrokerInterface):
    """Deterministic in-memory broker for UI and lifecycle development."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._orders: list[dict[str, Any]] = []
        self._quotes = [
            {"symbol": "NIFTY", "ltp": 24712.30, "change_pct": 0.42},
            {"symbol": "BANKNIFTY", "ltp": 54182.65, "change_pct": -0.18},
            {"symbol": "RELIANCE", "ltp": 1428.40, "change_pct": 0.73},
            {"symbol": "INFY", "ltp": 1536.90, "change_pct": -0.31},
        ]

    @property
    def name(self) -> str:
        return "paper"

    @property
    def is_authenticated(self) -> bool:
        return True

    def get_quotes(self) -> list[dict[str, Any]]:
        return self._quotes.copy()

    def get_positions(self) -> list[dict[str, Any]]:
        positions: dict[str, dict[str, Any]] = {}
        for order in self._orders:
            if order["status"] != "FILLED":
                continue
            position = positions.setdefault(
                order["symbol"],
                {"symbol": order["symbol"], "quantity": 0, "average_price": 0.0, "pnl": 0.0},
            )
            signed_quantity = order["quantity"] if order["side"] == "BUY" else -order["quantity"]
            position["quantity"] += signed_quantity
            position["average_price"] = order["price"]
        return list(positions.values())

    def get_orders(self) -> list[dict[str, Any]]:
        return list(reversed(self._orders))

    def place_order(self, order: dict[str, Any]) -> dict[str, Any]:
        if order["quantity"] > 1800:
            raise BrokerError("Paper risk limit: quantity cannot exceed 1,800.")
        if order["quantity"] * order["price"] > 500_000:
            raise BrokerError("Paper risk limit: order value cannot exceed ₹5,00,000.")
        created = {
            **order,
            "id": f"P-{uuid4().hex[:8].upper()}",
            "status": "FILLED" if order["order_type"] == "MARKET" else "OPEN",
            "created_at": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            self._orders.append(created)
        return created

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        with self._lock:
            for order in self._orders:
                if order["id"] == order_id and order["status"] == "OPEN":
                    order["status"] = "CANCELLED"
                    return order
        raise BrokerError("Only an open paper order can be cancelled.")
