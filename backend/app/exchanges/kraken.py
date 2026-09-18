import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import ccxt.async_support as ccxt
from app.core.config import settings
from app.exchanges.base import (
    ExchangeInterface,
    Ticker,
    OHLCV,
    OrderResult,
    OrderSide,
    OrderType,
    OrderStatus,
)


class KrakenExchange(ExchangeInterface):
    name = "kraken"
    is_live = True

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        key = api_key or settings.KRAKEN_API_KEY
        secret = api_secret or settings.KRAKEN_API_SECRET
        config = {"apiKey": key, "secret": secret, "enableRateLimit": True}
        self.client = ccxt.kraken(config)

    async def get_ticker(self, symbol: str) -> Ticker:
        ticker = await self.client.fetch_ticker(symbol)
        return Ticker(
            symbol=symbol,
            bid=ticker.get("bid"),
            ask=ticker.get("ask"),
            last=ticker.get("last", 0.0),
            volume=ticker.get("baseVolume"),
            timestamp=datetime.fromtimestamp(ticker["timestamp"] / 1000, tz=timezone.utc)
            if ticker.get("timestamp")
            else datetime.now(timezone.utc),
        )

    async def get_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> List[OHLCV]:
        candles = await self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return [
            OHLCV(
                timestamp=datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc),
                open=float(c[1]),
                high=float(c[2]),
                low=float(c[3]),
                close=float(c[4]),
                volume=float(c[5]),
            )
            for c in candles
        ]

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
    ) -> OrderResult:
        ccxt_side = side.value.lower()
        ccxt_type = "market" if order_type == OrderType.MARKET else "limit"
        params = {"price": price} if order_type == OrderType.LIMIT and price else {}
        order = await self.client.create_order(symbol, ccxt_type, ccxt_side, quantity, price, params)
        return self._order_to_result(order)

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        try:
            await self.client.cancel_order(order_id, symbol)
            return True
        except Exception:
            return False

    async def get_order_status(self, order_id: str, symbol: Optional[str] = None) -> OrderResult:
        order = await self.client.fetch_order(order_id, symbol)
        return self._order_to_result(order)

    async def get_balances(self) -> Dict[str, float]:
        balance = await self.client.fetch_balance()
        return balance.get("total", {})

    async def check_withdrawal_permission(self) -> bool:
        """Kraken scopes permissions per key; we cannot query scopes directly via API.
        We treat keys with withdrawal methods enabled as risky. This is a best-effort check.
        """
        try:
            await self.client.fetch_withdrawals()
            return True
        except Exception:
            return False

    def _order_to_result(self, order: Dict[Any, Any]) -> OrderResult:
        status_map = {
            "open": OrderStatus.PENDING,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELED,
            "rejected": OrderStatus.REJECTED,
        }
        return OrderResult(
            order_id=order.get("id"),
            status=status_map.get(order.get("status", ""), OrderStatus.PENDING),
            filled_qty=order.get("filled", 0.0),
            avg_price=order.get("average", 0.0) or order.get("price", 0.0),
            fee=order.get("fee", {}).get("cost", 0.0) or 0.0,
            raw_response=order,
        )
