"""Verify a cash difference against a continuous suffix of EUR funding entries."""
import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)


def funding_change(rows, previous_cash, current_cash):
    tolerance = Decimal('0.000001')
    old, current = Decimal(str(previous_cash)), Decimal(str(current_cash))
    cursor = current
    ids = []
    try:
        for row in sorted(rows, key=lambda item: Decimal(str(item['time'])), reverse=True):
            if row.get('asset') not in {'EUR', 'ZEUR'}:
                raise ValueError('Unexpected asset in EUR funding ledger')
            if row.get('type') not in {'deposit', 'withdrawal'}:
                break
            amount, fee, balance = (Decimal(str(row[key])) for key in ('amount', 'fee', 'balance'))
            if not all(value.is_finite() for value in (amount, fee, balance)) or fee < 0:
                raise ValueError('Invalid funding ledger amounts')
            if (row['type'] == 'deposit' and amount <= 0) or (row['type'] == 'withdrawal' and amount >= 0):
                raise ValueError('Invalid funding ledger direction')
            if abs(balance - cursor) > tolerance or not row.get('id') or row['id'] in ids:
                raise ValueError('Funding ledger does not match the current cash balance')
            ids.append(row['id'])
            cursor -= amount - fee
            if abs(cursor - old) <= tolerance:
                return float(current - old), ids
    except (InvalidOperation, KeyError, TypeError) as exc:
        raise ValueError('Invalid Kraken funding ledger; cash was not synchronized') from exc
    raise ValueError('EUR difference is not explained by recent deposits/withdrawals; manual reconciliation required')


async def reconcile_cash(db, portfolio, exchange, cash, balances):
    delta, ids = funding_change(await exchange.eur_ledger(), portfolio.cash, cash)
    # Recheck the snapshot after reading the ledger, before committing money values.
    fresh = await exchange.get_balances()
    if fresh != balances:
        raise ValueError('Kraken balances changed during cash synchronization; retry next cycle')
    if await exchange.open_orders():
        raise ValueError('Open exchange orders prevent cash synchronization')
    portfolio.cash = cash
    portfolio.equity += delta
    portfolio.initial_equity += delta
    portfolio.peak_equity = max(0., portfolio.peak_equity + delta)
    # A deposit must never reset a previously triggered risk halt.
    db.commit()
    logger.info('Verified funding adjustment for portfolio %s: %.8f EUR, ledger IDs %s',
                portfolio.id, delta, ','.join(ids))
