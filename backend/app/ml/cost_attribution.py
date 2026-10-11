"""Account for costs on the observed fill path; never claim a zero-cost strategy result."""
from collections import defaultdict, deque
from datetime import datetime, timezone
import math


def timestamp(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(str(value))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def attribution(result):
    slip=(result.get('experiment',{}).get('configuration',{}).get('risk',{})).get('slippage_pct')
    if slip is not None and (not math.isfinite(slip) or not 0<=slip<1):
        raise ValueError('Invalid modeled slippage')
    lots=defaultdict(deque); rounds=[]; limitations=[]
    for trade in result.get('trades',[]):
        symbol=trade['symbol']; side=trade['side']
        quantity=float(trade['quantity']); price=float(trade['price']); fee=float(trade['fee'])
        if not all(math.isfinite(value) for value in (quantity,price,fee)) or quantity<=0 or price<=0 or fee<0:
            raise ValueError('Invalid fill accounting')
        stamp=timestamp(trade['timestamp'])
        if side=='BUY':
            lots[symbol].append({'quantity':quantity,'price':price,'fee_per_unit':fee/quantity,'stamp':stamp})
            continue
        if side!='SELL':
            raise ValueError('Unknown fill side')
        remaining=quantity; entry_fees=price_pnl=entry_slip=weighted_hours=0.
        while remaining>1e-9 and lots[symbol]:
            lot=lots[symbol][0]; matched=min(remaining,lot['quantity'])
            entry_fees+=matched*lot['fee_per_unit']
            price_pnl+=matched*(price-lot['price'])
            weighted_hours+=matched*(stamp-lot['stamp']).total_seconds()/3600
            if slip is not None:
                entry_slip+=matched*(lot['price']-lot['price']/(1+slip))
            remaining-=matched; lot['quantity']-=matched
            if lot['quantity']<=1e-9:
                lots[symbol].popleft()
        if remaining>1e-9:
            raise ValueError('Exit lacks matching entry evidence')
        net=price_pnl-entry_fees-fee
        if trade.get('pnl') is not None and not math.isclose(net,float(trade['pnl']),rel_tol=1e-7,abs_tol=1e-7):
            raise ValueError('Closed P&L does not reconcile to fills and fees')
        slippage=entry_slip+quantity*(price/(1-slip)-price) if slip is not None else None
        rounds.append({'symbol':symbol,'month':stamp.strftime('%Y-%m'),
            'exit_reason':trade.get('reason') or 'Unrecorded','net_pnl':net,
            'fees':entry_fees+fee,'modeled_slippage':slippage,
            'before_fees_pnl':price_pnl,'before_modeled_costs_pnl':price_pnl+slippage if slippage is not None else None,
            'holding_hours':weighted_hours/quantity})
    def aggregate(rows):
        fees=sum(row['fees'] for row in rows); net=sum(row['net_pnl'] for row in rows)
        slippage=sum(row['modeled_slippage'] for row in rows) if slip is not None else None
        return {'closed_trades':len(rows),'net_pnl':net,'closed_fees':fees,'modeled_slippage':slippage,
            'same_fill_path_before_fees_pnl':net+fees,
            'same_fill_path_before_modeled_costs_pnl':net+fees+slippage if slippage is not None else None,
            'average_holding_hours':sum(row['holding_hours'] for row in rows)/len(rows) if rows else None,
            'fee_share_of_net_loss':fees/-net if net<0 else None}
    totals=aggregate(rounds)
    all_fees=sum(float(trade['fee']) for trade in result.get('trades',[]))
    expected_fees=result.get('total_fees')
    if expected_fees is not None and not math.isclose(all_fees,expected_fees,rel_tol=1e-7,abs_tol=1e-7):
        raise ValueError('Total fees do not reconcile')
    open_net=0.; open_positions=result.get('open_positions',{})
    for symbol,queue in lots.items():
        if not queue:
            continue
        mark=(open_positions.get(symbol) or {}).get('current_price')
        if mark is None:
            limitations.append('Open holdings lack mark evidence; equity reconciliation unavailable')
            open_net=None; break
        open_net+=sum((float(mark)-lot['price'])*lot['quantity']-lot['fee_per_unit']*lot['quantity'] for lot in queue)
    equity_pnl=(result['final_equity']-result['initial_cash']) if 'final_equity' in result and 'initial_cash' in result else None
    residual=equity_pnl-totals['net_pnl']-open_net if equity_pnl is not None and open_net is not None else None
    if any(row['exit_reason']=='Unrecorded' for row in rounds):
        limitations.append('Historical exit reasons were not recorded and are not inferred')
    if slip is None:
        limitations.append('Modeled slippage unavailable; it is not assumed to be zero')
    groups={}
    for field in ('symbol','month','exit_reason'):
        keys=sorted({row[field] for row in rounds})
        groups[field]={key:aggregate([row for row in rounds if row[field]==key]) for key in keys}
    return {**totals,'total_recorded_fees':all_fees,'open_marked_pnl':open_net,
        'equity_pnl':equity_pnl,'equity_reconciliation_residual':residual,'groups':groups,
        'limitations':limitations+['Costs are attributed to identical recorded quantities and fills; removing costs would change trading decisions.',
                                   'Historical spread/depth and regime attribution are unavailable unless explicitly recorded.']}
