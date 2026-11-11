from datetime import UTC, datetime
import math
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
        with self._lock:
            return [dict(q) for q in self._quotes]

    def get_positions(self) -> list[dict[str, Any]]:
        with self._lock:
            orders = [dict(o) for o in self._orders if o["status"] == "FILLED"]

        state: dict[str, dict[str, float]] = {}
        for order in orders:
            symbol = order["symbol"]
            entry = state.setdefault(
                symbol,
                {"quantity": 0, "total_cost": 0.0, "realized_pnl": 0.0},
            )
            order_qty = order["quantity"]
            price = float(order["price"])
            signed = order_qty if order["side"] == "BUY" else -order_qty
            qty = entry["quantity"]

            if qty == 0 or qty * signed > 0:
                entry["quantity"] = qty + signed
                entry["total_cost"] += order_qty * price
            else:
                abs_qty = abs(qty)
                avg_price = entry["total_cost"] / abs_qty
                closed = min(abs_qty, order_qty)
                if qty > 0:
                    entry["realized_pnl"] += closed * (price - avg_price)
                else:
                    entry["realized_pnl"] += closed * (avg_price - price)

                new_qty = qty + signed
                entry["quantity"] = new_qty
                if order_qty < abs_qty:
                    entry["total_cost"] = avg_price * abs(new_qty)
                elif order_qty == abs_qty:
                    entry["total_cost"] = 0.0
                else:
                    entry["total_cost"] = abs(new_qty) * price

        return [
            {
                "symbol": symbol,
                "quantity": int(pos["quantity"]),
                "average_price": round(pos["total_cost"] / abs(pos["quantity"]), 6) if pos["quantity"] != 0 else 0.0,
                "pnl": round(pos["realized_pnl"], 6),
            }
            for symbol, pos in state.items()
        ]

    def get_orders(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(o) for o in reversed(self._orders)]

    def place_order(self, order: dict[str, Any]) -> dict[str, Any]:
        symbol = order.get("symbol")
        side = order.get("side")
        order_type = order.get("order_type")
        quantity = order.get("quantity")
        price = order.get("price")

        if not isinstance(symbol, str) or not symbol.strip():
            raise BrokerError("Instrument symbol is required.")
        if side not in ("BUY", "SELL"):
            raise BrokerError("Order side must be BUY or SELL.")
        if order_type not in ("MARKET", "LIMIT"):
            raise BrokerError("Order type must be MARKET or LIMIT.")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise BrokerError("Order quantity must be a positive integer.")
        if quantity > 1800:
            raise BrokerError("Paper risk limit: quantity cannot exceed 1,800.")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise BrokerError("Order price must be a positive finite number.")
        if quantity * price > 500_000:
            raise BrokerError("Paper risk limit: order value cannot exceed ₹5,00,000.")
        created = {
            **order,
            "symbol": symbol.strip(),
            "id": f"P-{uuid4().hex[:8].upper()}",
            "status": "FILLED" if order_type == "MARKET" else "OPEN",
            "created_at": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            self._orders.append(created)
        return dict(created)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        with self._lock:
            for order in self._orders:
                if order["id"] == order_id and order["status"] == "OPEN":
                    order["status"] = "CANCELLED"
                    return dict(order)
        raise BrokerError("Only an open paper order can be cancelled.")
