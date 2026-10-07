"""Read-only entry preflight for dashboard eligibility; never submits an order."""
import asyncio
import math
from datetime import datetime, timezone

from app.services.memecoin_service import check_liquidity
from app.services.risk_service import entry_budget
from app.services.momentum_policy import depth_capacity
from app.exchanges.universe import is_memecoin


async def entry_readiness(exchange, portfolio, risk, symbol, positions, histories):
    checked_at=datetime.now(timezone.utc).isoformat()
    result={'eligible':False,'checked_at':checked_at}
    if risk.entry_strategy == 'fast_momentum' and not is_memecoin(symbol):
        return {**result,'code':'meme_focus','message':'Fast meme momentum opens memecoin positions only.'}
    minimum = 30 if risk.entry_strategy in {'momentum','fast_momentum','auto'} else 336
    if len(histories.get(symbol,[])) < minimum:
        return {**result,'code':'insufficient_history','message':f'Fewer than {minimum} usable hourly candles; collecting history before eligibility checks.'}
    budget=entry_budget(portfolio,risk,symbol,positions,histories)
    if budget<=.01:
        return {**result,'code':'allocation','message':'No available allocation under the current cash and exposure limits.'}
    try:
        liquidity=await asyncio.wait_for(check_liquidity(exchange,symbol,risk),timeout=10)
        if risk.entry_strategy == 'fast_momentum' and liquidity:
            budget=min(budget,liquidity[0]*.001)
        ticker=await asyncio.wait_for(exchange.get_ticker(symbol),timeout=10)
        price=ticker.ask or ticker.last
        if not math.isfinite(price) or price<=0: raise ValueError('Usable ask price unavailable')
        quantity=budget/(price*(1+risk.slippage_pct)*(1+risk.fee_pct))
        adapter=exchange.market if hasattr(exchange,'market') else exchange
        if not hasattr(adapter,'prepare_order'):
            return {**result,'code':'preflight_unavailable','message':'Exchange order minimums and precision have not been verified.'}
        if risk.entry_strategy == 'fast_momentum':
            book=await asyncio.wait_for(adapter.get_order_book(symbol),timeout=10)
            quantity=min(quantity,depth_capacity(book,price,float(ticker.bid or 0),risk.slippage_pct))
        await asyncio.wait_for(adapter.prepare_order(symbol,quantity,price),timeout=10)
        return {**result,'eligible':True,'code':'eligible','message':'Latest market, history and order-size checks passed. Final execution checks still apply.'}
    except Exception as exc:
        # Preserve the original validation reason instead of masking it as a vague market preflight failure.
        if isinstance(exc, ValueError):
            message = str(exc).strip() or 'Market preflight unavailable'
        else:
            message = f'Market preflight unavailable ({type(exc).__name__})'
        return {**result,'code':'market_blocked','message':message}
