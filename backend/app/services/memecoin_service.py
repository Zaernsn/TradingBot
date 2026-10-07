"""Kraken memecoin eligibility and execution guards."""
from math import isfinite, log1p
import asyncio
import time
from datetime import datetime, timezone
from app.exchanges.universe import CURATED_PAIRS, is_memecoin


class LiquidityLimitError(ValueError):
    """An expected, temporary market condition that makes an entry ineligible."""


async def eligible_universe(exchange, risk, diagnostics=None):
    if not risk.memecoins_enabled: return list(CURATED_PAIRS)
    adapter=exchange.market if hasattr(exchange,'market') else exchange
    from app.services.meme_discovery import meme_symbols
    symbols = await meme_symbols()
    markets = await adapter.client.load_markets(reload=True)
    ranked = []
    started=time.monotonic()
    candidates=[symbol for symbol,market in markets.items() if market.get('base') in symbols and is_memecoin(symbol)
                and market.get('spot') is True and market.get('active') is True and market.get('quote')=='EUR']
    limiter=asyncio.Semaphore(4)
    statuses={}
    async def inspect(symbol):
        try:
            async with limiter:
                ticker = await asyncio.wait_for(adapter.client.fetch_ticker(symbol),timeout=10)
            turnover, spread = validate_liquidity(ticker, risk, enforce_limits=False)
            momentum = float(ticker.get('percentage') or 0)
            if not isfinite(momentum): momentum = 0
            score = log1p(turnover) * (1 + max(-.5, min(.5, momentum / 100))) / (1 + spread * 1000)
            try:
                validate_liquidity(ticker,risk)
                eligible=True; reason=None
            except ValueError as exc:
                eligible=False; reason=str(exc)
            statuses[symbol]={'market_eligible':eligible,'reason':reason,'turnover_eur':turnover,'spread_pct':spread,
                              'checked_at':datetime.now(timezone.utc).isoformat()}
            ranked.append((symbol, score, eligible))
        except Exception as exc:
            statuses[symbol]={'market_eligible':False,'reason':f'Quote unavailable ({type(exc).__name__})',
                              'checked_at':datetime.now(timezone.utc).isoformat()}
    await asyncio.gather(*(inspect(symbol) for symbol in candidates))
    ranked.sort(key=lambda item: (not item[2], -item[1], item[0]))
    limit=getattr(risk,'discovery_limit',60)
    if diagnostics is not None:
        diagnostics.update(discovered=len(candidates),quoted=len(ranked),
            market_eligible=sum(row[2] for row in ranked),retained=min(limit,len(ranked)),
            quote_requests=len(candidates),quote_failures=len(candidates)-len(ranked),
            scan_seconds=round(time.monotonic()-started,3),checked_at=datetime.now(timezone.utc).isoformat(),
            markets=statuses,coverage='Kraken category page coverage; not an exhaustive market catalogue')
    # Monitoring is broader than permission to buy; entry liquidity is rechecked strictly.
    return list(CURATED_PAIRS) + [symbol for symbol, _, _ in ranked[:limit]]


async def check_liquidity(exchange,symbol,risk):
    if not is_memecoin(symbol): return
    if not risk.memecoins_enabled: raise ValueError('Memecoin entries are disabled')
    adapter=exchange.market if hasattr(exchange,'market') else exchange
    ticker=await adapter.client.fetch_ticker(symbol)
    return validate_liquidity(ticker, risk)


def validate_liquidity(ticker, risk, enforce_limits=True):
    try:
        bid=float(ticker['bid']); ask=float(ticker['ask']); last=float(ticker['last'])
        turnover=ticker.get('quoteVolume')
        if turnover is None: turnover=float(ticker['baseVolume'])*last
        turnover=float(turnover)
        if not all(isfinite(v) and v>0 for v in [bid,ask,last,turnover]) or ask<bid: raise ValueError()
    except (KeyError,TypeError,ValueError):
        raise ValueError('Memecoin quote/liquidity data unavailable')
    spread=(ask-bid)/((ask+bid)/2)
    if enforce_limits and spread>risk.memecoin_max_spread_pct:
        raise LiquidityLimitError(
            f'Spread is currently {spread:.2%}; your maximum is {risk.memecoin_max_spread_pct:.2%}. '
            'Waiting for a tighter quote.'
        )
    if enforce_limits and turnover<risk.memecoin_min_daily_volume_eur:
        raise LiquidityLimitError(
            f'24-hour EUR turnover is currently €{turnover:,.0f}; your minimum is '
            f'€{risk.memecoin_min_daily_volume_eur:,.0f}. Waiting for more liquidity.'
        )
    return turnover, spread


def memecoin_budget(portfolio,risk,symbol,positions):
    if not is_memecoin(symbol): return float('inf')
    if not getattr(risk, 'memecoins_enabled', False): return 0.
    exposure=sum(p.quantity*p.current_price for p in positions if is_memecoin(p.symbol))
    max_position_pct = getattr(risk, 'memecoin_max_position_pct', 0.05)
    max_exposure_pct = getattr(risk, 'memecoin_max_exposure_pct', 0.10)
    return max(0.,min(portfolio.equity*max_position_pct,
                      portfolio.equity*max_exposure_pct-exposure))
