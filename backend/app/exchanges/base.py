from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


@dataclass
class Ticker:
    symbol: str
    bid: Optional[float]
    ask: Optional[float]
    last: float
    volume: Optional[float]
    timestamp: datetime


@dataclass
class OHLCV:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class OrderResult:
    order_id: Optional[str]
    status: OrderStatus
    filled_qty: float
    avg_price: float
    fee: float
    raw_response: Optional[Dict[Any, Any]] = None


class ExchangeInterface(ABC):
    name: str = "base"
    is_live: bool = False

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        pass

    @abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> List[OHLCV]:
        pass

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
    ) -> OrderResult:
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str, symbol: Optional[str] = None) -> OrderResult:
        pass

    @abstractmethod
    async def get_balances(self) -> Dict[str, float]:
        pass

    @abstractmethod
    async def check_withdrawal_permission(self) -> bool:
        """Return True if the API key has any withdrawal permission."""
        pass
