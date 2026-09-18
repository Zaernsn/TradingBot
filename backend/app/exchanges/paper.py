from datetime import datetime, timezone
from typing import List, Optional, Dict
from app.exchanges.base import (
    ExchangeInterface,
    Ticker,
    OHLCV,
    OrderResult,
    OrderSide,
    OrderType,
    OrderStatus,
)
from app.exchanges.kraken import KrakenExchange


class PaperExchange(ExchangeInterface):
    """Paper exchange uses live market data from Kraken but never submits real orders."""

    name = "paper"
    is_live = False

    def __init__(self):
        self.market = KrakenExchange(api_key="", api_secret="")

    async def get_ticker(self, symbol: str) -> Ticker:
        return await self.market.get_ticker(symbol)

    async def get_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> List[OHLCV]:
        return await self.market.get_ohlcv(symbol, timeframe=timeframe, limit=limit)

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
    ) -> OrderResult:
        ticker = await self.get_ticker(symbol)
        fill_price = price if order_type == OrderType.LIMIT and price else ticker.last
        return OrderResult(
            order_id=f"paper-{datetime.now(timezone.utc).isoformat()}",
            status=OrderStatus.FILLED,
            filled_qty=quantity,
            avg_price=fill_price,
            fee=0.0,
            raw_response={"paper": True, "symbol": symbol, "side": side.value},
        )

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        return True

    async def get_order_status(self, order_id: str, symbol: Optional[str] = None) -> OrderResult:
        return OrderResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            filled_qty=0.0,
            avg_price=0.0,
            fee=0.0,
        )

    async def get_balances(self) -> Dict[str, float]:
        return {}

    async def check_withdrawal_permission(self) -> bool:
        return False
