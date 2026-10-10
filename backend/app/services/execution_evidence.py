"""Passive order evidence. Observation times are not exchange fill timestamps."""
import math
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (ValueError, TypeError):
        return None


def decision_context(ticker=None, book=None):
    context = {'decision_at': now_iso()}
    if ticker is not None:
        bid, ask = positive(ticker.bid), positive(ticker.ask)
        stamp = getattr(ticker, 'timestamp', None)
        context.update(bid=bid, ask=ask, quote_at=stamp.isoformat() if isinstance(stamp, datetime) else None,
                       quote_source=getattr(ticker, 'source', None),
                       spread_pct=(ask-bid)/((ask+bid)/2) if bid and ask and ask >= bid else None)
    if book is not None:
        # Public book only, bounded evidence; no authenticated raw responses.
        levels = {}
        for side in ('bids', 'asks'):
            levels[side] = [[float(p), float(q)] for p, q, *_ in book.get(side, [])[:100]
                            if positive(p) and positive(q)]
        context['depth'] = {**levels, 'timestamp': book.get('timestamp'), 'source': book.get('source')}
    return context


def elapsed_ms(start, end):
    if not start or not end:
        return None
    try:
        a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if a.tzinfo is None or b.tzinfo is None:
            return None
        value = (b-a).total_seconds()*1000
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


def report(order):
    evidence = order.execution_evidence or {}
    filled = order.filled_quantity or 0.
    average = order.filled_cost/filled if filled > 0 else None
    reference = positive(evidence.get('ask' if order.side == 'BUY' else 'bid'))
    # Positive means adverse execution for either side. Fees remain separate.
    slippage = ((average/reference-1)*(1 if order.side == 'BUY' else -1)
                if average and reference else None)
    return {**evidence, 'average_fill_price': average,
            'remaining_quantity': max(0., order.requested_quantity-filled),
            'quote_fee_eur': order.filled_fee, 'base_fee': order.filled_base_fee,
            'base_fee_currency': order.symbol.split('/')[0],
            'realized_slippage_pct': slippage,
            'decision_to_submit_ms': elapsed_ms(evidence.get('decision_at'), evidence.get('submission_started_at')),
            'submit_to_ack_ms': elapsed_ms(evidence.get('submission_started_at'), evidence.get('acknowledged_at')),
            'submit_to_first_fill_observed_ms': elapsed_ms(evidence.get('submission_started_at'), evidence.get('first_fill_observed_at')),
            'quote_age_at_submit_ms': elapsed_ms(evidence.get('quote_at'), evidence.get('submission_started_at')),
            'limitations': ['Fill times are local REST observations, not exchange execution timestamps.',
                            'Slippage includes price movement and impact; these cannot be separated from this evidence alone.']}
