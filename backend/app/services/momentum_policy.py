"""Shared fast-momentum entry controls; no exchange side effects."""
import math


def depth_capacity(book, ask, bid, slippage):
    """Use at most 5% of both buy and stressed sell depth, in base units."""
    if not all(math.isfinite(v) and v > 0 for v in (ask, bid)) or bid > ask:
        raise ValueError('Invalid entry quote')
    def quantity(side, eligible):
        levels = book.get(side) or []
        total = 0.
        for row in levels:
            price, size = float(row[0]), float(row[1])
            if not math.isfinite(price) or not math.isfinite(size) or price <= 0 or size < 0:
                raise ValueError('Invalid order-book depth')
            if eligible(price):
                total += size
        return total
    buy = quantity('asks', lambda price: price <= ask * (1 + slippage))
    sell = quantity('bids', lambda price: price >= bid * (1 - slippage))
    return .05 * min(buy, sell)


def fast_meme_preset(config):
    """Preserve allocation/fee choices while allowing stronger candidate discovery."""
    config.entry_strategy = 'fast_momentum'
    config.buy_probability_threshold = .4
    config.memecoins_enabled = True
    config.memecoin_min_daily_volume_eur = max(config.memecoin_min_daily_volume_eur, 250000.)
    config.memecoin_max_spread_pct = min(config.memecoin_max_spread_pct, .006)
    config.max_holding_hours = min(config.max_holding_hours or 24, 24)
    return config
