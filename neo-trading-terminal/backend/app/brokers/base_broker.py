from abc import ABC, abstractmethod
from typing import Any


class BrokerError(RuntimeError):
    """Safe, user-facing broker failure."""


class BrokerInterface(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def is_authenticated(self) -> bool: ...

    @abstractmethod
    def get_quotes(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_orders(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def place_order(self, order: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict[str, Any]: ...
