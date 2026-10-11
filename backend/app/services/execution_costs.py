"""Read-only cost evidence for one user's live orders and public watched markets."""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from app.models.portfolio import ExecutionOrder, Portfolio, BotState
from app.services.execution_evidence import report, positive
from app.services.market_observations import observation_summary, MAX_AGE_SECONDS


def execution_cost_report(db,user_id,now=None):
    now=now or datetime.now(timezone.utc)
    orders=db.query(ExecutionOrder).join(Portfolio,ExecutionOrder.portfolio_id==Portfolio.id).filter(
        Portfolio.user_id==user_id,Portfolio.book_type=='LIVE',
        ExecutionOrder.created_at>=now-timedelta(days=30),ExecutionOrder.created_at<=now).order_by(
        ExecutionOrder.created_at.desc()).limit(500).all()
    filled=[order for order in orders if positive(order.filled_quantity)]
    measured=[]; base_fees=defaultdict(float)
    for order in filled:
        item=report(order)
        base_fees[order.symbol.split('/')[0]]+=order.filled_base_fee or 0.
        age=item.get('quote_age_at_submit_ms')
        bid,ask=positive(item.get('bid')),positive(item.get('ask'))
        reference=ask if order.side=='BUY' else bid
        if age is None or not 0<=age<=MAX_AGE_SECONDS*1000 or not bid or not ask or bid>ask or not reference:
            continue
        price=item['average_fill_price']
        if not positive(price):
            continue
        measured.append({'symbol':order.symbol,'side':order.side,'quantity':order.filled_quantity,
            'adverse_vs_touch_eur':(price-reference)*order.filled_quantity*(1 if order.side=='BUY' else -1),
            'quote_fee_eur':order.filled_fee,'remaining_quantity':item['remaining_quantity']})
    state=db.query(BotState).filter_by(user_id=user_id).first()
    from app.exchanges.universe import CURATED_PAIRS
    symbols=(state.watchlist or []) if state else []
    return {'public_markets':observation_summary(db,symbols or CURATED_PAIRS,now),
        'live_execution':{'window_days':30,'orders':len(orders),'filled_orders':len(filled),
            'fresh_quote_matched_orders':len(measured),
            'quote_fee_eur':sum(order.filled_fee or 0. for order in filled) if filled else None,
            'base_fees_by_currency':{currency:amount for currency,amount in base_fees.items() if amount},
            'adverse_vs_touch_eur':sum(item['adverse_vs_touch_eur'] for item in measured) if measured else None,
            'matched_fill_measurements':measured,
            'limitations':['At most 500 recent live orders; paper fills are excluded.',
                'Only fresh decision quotes are matched; no later archived quote substitutes for missing evidence.',
                'Adverse execution includes movement and impact; base-currency fees are not converted into invented EUR costs.']}}
