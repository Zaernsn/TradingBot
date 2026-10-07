"""Read-only Kraken account valuations, separate from bot trading books."""
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
from app.models.portfolio import KrakenSnapshot
from app.services.exchange_service import decrypt_value
from app.exchanges.kraken import KrakenExchange


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def value_holdings(client):
    balance = await client.fetch_balance()
    markets = await client.load_markets()
    if not isinstance(balance.get('total'), dict):
        raise ValueError('Balance totals unavailable')
    holdings = []
    for asset, amount in (balance.get('total') or {}).items():
        if amount is None: continue
        amount = float(amount)
        if not isfinite(amount): raise ValueError('Invalid balance')
        if amount == 0: continue
        price = 1. if asset == 'EUR' else None
        if price is None:
            direct, inverse = f'{asset}/EUR', f'EUR/{asset}'
            symbol = direct if direct in markets else inverse if inverse in markets else None
            if symbol:
                try:
                    ticker = await client.fetch_ticker(symbol)
                    last = float(ticker['last'])
                    if isfinite(last) and last > 0: price = last if symbol == direct else 1 / last
                except Exception:
                    pass
        holdings.append({'asset': asset, 'quantity': amount, 'price': price, 'value': amount * price if price is not None else None})
    return holdings


async def account_overview(db, user):
    if not user.kraken_api_key_encrypted or not user.kraken_api_secret_encrypted:
        return {'connected': False, 'history': [], 'holdings': [], 'equity': None}
    key = decrypt_value(user.kraken_api_key_encrypted)
    fingerprint = sha256(key.encode()).hexdigest()
    query = db.query(KrakenSnapshot).filter(KrakenSnapshot.user_id == user.id, KrakenSnapshot.account_key == fingerprint)
    latest = query.order_by(KrakenSnapshot.captured_at.desc()).first()
    now = datetime.now(timezone.utc)
    if latest is None or (now - utc(latest.captured_at)).total_seconds() >= 300:
        exchange = KrakenExchange(api_key=key, api_secret=decrypt_value(user.kraken_api_secret_encrypted))
        try:
            holdings = await value_holdings(exchange.client)
        finally:
            await exchange.close()
        equity = sum(h['value'] for h in holdings) if all(h['value'] is not None for h in holdings) else None
        latest = KrakenSnapshot(user_id=user.id, account_key=fingerprint, captured_at=now, equity=equity, holdings=holdings)
        db.add(latest); db.commit(); db.refresh(latest)
    history = query.order_by(KrakenSnapshot.captured_at.asc()).all()
    return {'connected': True, 'equity': latest.equity, 'holdings': latest.holdings,
            'captured_at': utc(latest.captured_at).isoformat(),
            'history': [{'timestamp': utc(row.captured_at).isoformat(), 'value': row.equity} for row in history]}
