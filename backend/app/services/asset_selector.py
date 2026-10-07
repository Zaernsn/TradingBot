"""Rank daily market data without placing orders or making network requests."""
from math import isfinite, sqrt
from statistics import mean, stdev


class AssetSelector:
    def select_watchlist(self, ohlcv_by_symbol, max_open_positions=5, memecoins_enabled=False,
                         eligibility=None, previous=None, limit=30, monitor_all=False):
        """Keep a dedicated meme shortlist independent of concurrent position slots."""
        from app.exchanges.universe import CURATED_PAIRS, is_memecoin, MEMECOIN_WATCHLIST_TARGET, WATCHLIST_LIMIT
        core = {s: rows for s, rows in ohlcv_by_symbol.items() if s in CURATED_PAIRS}
        selected = self.select(core, min(max_open_positions,limit))
        monitored=[]
        if memecoins_enabled:
            memes = {s: rows for s, rows in ohlcv_by_symbol.items() if is_memecoin(s)}
            # Prioritize qualifying momentum; continue monitoring other liquid candidates.
            ranked = self.select(memes, MEMECOIN_WATCHLIST_TARGET, timeframe='1h')
            monitored = ranked + [s for s in memes if s not in ranked]
            if eligibility is not None:
                # Eligible first; retain existing members within the same tier to limit churn.
                order={s:i for i,s in enumerate(monitored)}
                def priority(symbol):
                    status=eligibility.get(symbol,{})
                    ready=status.get('market_eligible') is True and status.get('history_eligible') is True
                    model=status.get('model_ready')
                    tier=0 if ready and model is True else 1 if ready and model is None else 2 if ready else 3
                    return (tier,symbol not in (previous or []),order[symbol])
                monitored.sort(key=priority)
        result=monitored[:max(0,min(WATCHLIST_LIMIT,limit) - len(selected))] + selected
        if monitor_all and len(result)<min(WATCHLIST_LIMIT,limit):
            # Automatic mode needs a representative basket even when no market
            # currently has positive selection momentum. Monitoring is not an
            # entry approval: every symbol still needs an explicit BUY plus fresh
            # liquidity, order-size and risk checks.
            available=set(ohlcv_by_symbol)
            remainder=([s for s in (previous or []) if s in available and s not in result] +
                       [s for s in sorted(available) if s not in result and s not in (previous or [])])
            result.extend(remainder[:min(WATCHLIST_LIMIT,limit)-len(result)])
        return result

    def __init__(self, min_volatility=0.05, max_volatility=2.0, lookback=30):
        self.min_volatility = min_volatility
        self.max_volatility = max_volatility
        self.lookback = max(8, lookback)

    def select(self, ohlcv_by_symbol, max_open_positions=5, timeframe='1d') -> list[str]:
        if timeframe not in {'1h', '1d'}:
            raise ValueError('Selection requires hourly or daily candles')
        periods_per_year = 365 * (24 if timeframe == '1h' else 1)
        scored = []
        for symbol, candles in ohlcv_by_symbol.items():
            if len(candles) < self.lookback:
                continue
            try:
                recent = candles[-self.lookback:]
                closes = [float(c['close'] if isinstance(c, dict) else c.close) for c in recent]
                volumes = [float(c['volume'] if isinstance(c, dict) else c.volume) for c in recent]
                if any(not isfinite(c) or c <= 0 for c in closes):
                    continue
                if any(not isfinite(v) or v < 0 for v in volumes) or mean(volumes) <= 0:
                    continue
                returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
                volatility = stdev(returns[-7:]) * sqrt(periods_per_year)
                if not self.min_volatility <= volatility <= self.max_volatility:
                    continue
                if closes[-1] <= closes[-8] or closes[-1] <= mean(closes):
                    continue  # Positive trend required; cash is a valid selection.
                momentum = (closes[-1] / closes[-8] - 1) / max(volatility, 1e-8)
                score = momentum * (mean(volumes[-7:]) / mean(volumes))
                scored.append((symbol, score))
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                continue
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [symbol for symbol, _ in scored[:max(1, min(30, max_open_positions))]]
