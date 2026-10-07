import asyncio
import hashlib
import logging
import math
import random
import threading
import time
import weakref
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import ccxt.async_support as ccxt
from app.core.config import settings
from app.exchanges.base import (
    ExchangeInterface,
    Ticker,
    OHLCV,
    OrderResult,
    OrderSide,
    OrderType,
    OrderStatus,
)


logger = logging.getLogger(__name__)


class _CoordinatedKrakenClient(ccxt.kraken):
    """Keep Kraken private-request nonces ordered across adapter instances.

    CCXT 4.3.50 uses millisecond timestamps. A key previously used by a client
    with microsecond nonces will therefore reject CCXT's smaller values, and
    separate CCXT instances can also send equal or out-of-order values.
    """

    _state_lock = threading.Lock()
    _last_nonce_by_key: dict[str, int] = {}
    _request_locks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    def _key_id(self) -> str:
        # Do not retain an API key in process-wide coordination state.
        return hashlib.sha256(self.encode(self.apiKey or '')).hexdigest()

    def nonce(self):
        key_id = self._key_id()
        candidate = time.time_ns() // 1_000
        with self._state_lock:
            value = max(candidate, self._last_nonce_by_key.get(key_id, 0) + 1)
            self._last_nonce_by_key[key_id] = value
        return value

    def _private_request_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        key_id = self._key_id()
        with self._state_lock:
            locks_for_loop = self._request_locks.setdefault(loop, {})
            return locks_for_loop.setdefault(key_id, asyncio.Lock())

    async def request(self, path, api='public', method='GET', params=None,
                      headers=None, body=None, config=None):
        params = {} if params is None else params
        config = {} if config is None else config
        if api != 'private':
            return await super().request(path, api, method, params, headers, body, config)
        # Ordering nonce generation is insufficient on its own: concurrent
        # requests may reach Kraken in the opposite order.
        async with self._private_request_lock():
            return await super().request(path, api, method, params, headers, body, config)


class OrderRejected(ValueError):
    """Kraken explicitly rejected AddOrder before an order was accepted."""


class KrakenPreflightError(ValueError):
    """Sanitized private preflight failure with explicit retry semantics."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class KrakenExchange(ExchangeInterface):
    name = "kraken"
    is_live = True

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        key = settings.KRAKEN_API_KEY if api_key is None else api_key
        secret = settings.KRAKEN_API_SECRET if api_secret is None else api_secret
        config = {"apiKey": key, "secret": secret, "enableRateLimit": True}
        self.client = _CoordinatedKrakenClient(config)
        self._sleep = asyncio.sleep

    async def close(self):
        await self.client.close()

    async def get_ticker(self, symbol: str) -> Ticker:
        ticker = await self.client.fetch_ticker(symbol)
        return Ticker(
            symbol=symbol,
            bid=ticker.get("bid"),
            ask=ticker.get("ask"),
            last=ticker.get("last", 0.0),
            volume=ticker.get("baseVolume"),
            timestamp=datetime.fromtimestamp(ticker["timestamp"] / 1000, tz=timezone.utc)
            if ticker.get("timestamp")
            else datetime.now(timezone.utc),
        )

    async def get_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> List[OHLCV]:
        candles = await self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return [
            OHLCV(
                timestamp=datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc),
                open=float(c[1]),
                high=float(c[2]),
                low=float(c[3]),
                close=float(c[4]),
                volume=float(c[5]),
            )
            for c in candles
        ]

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
    ) -> OrderResult:
        ccxt_side = side.value.lower()
        ccxt_type = "market" if order_type == OrderType.MARKET else "limit"
        params = {"price": price} if order_type == OrderType.LIMIT and price else {}
        order = await self.client.create_order(symbol, ccxt_type, ccxt_side, quantity, price, params)
        return self._order_to_result(order)

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        try:
            await self.client.cancel_order(order_id, symbol)
            return True
        except Exception:
            return False

    async def get_order_status(self, order_id: str, symbol: Optional[str] = None) -> OrderResult:
        order = await self.client.fetch_order(order_id, symbol)
        return self._order_to_result(order)

    async def get_balances(self) -> Dict[str, float]:
        balance = await self.client.fetch_balance()
        return balance.get("total", {})

    async def eur_ledger(self):
        # Keep all EUR activity: filtering to deposits would hide external trades.
        try:
            response = await self.client.request('Ledgers', 'private', 'POST', {'asset': 'ZEUR'})
        except Exception as exc:
            raise ValueError('Cannot verify cash changes. Enable Data - Query ledger entries on the Kraken API key and retry.') from exc
        if response.get('error') or not isinstance(response.get('result', {}).get('ledger'), dict):
            raise ValueError('Kraken EUR ledger unavailable; cash was not synchronized')
        return [dict(row, id=key) for key, row in response['result']['ledger'].items()]

    async def permissions(self) -> set[str]:
        # Use the documented endpoint, even with older CCXT endpoint catalogs.
        response = await self.client.request('GetApiKeyInfo', 'private', 'POST', {})
        permissions = response.get('result', {}).get('permissions')
        if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
            raise ValueError('Unable to verify Kraken API permissions')
        return set(permissions)

    async def check_withdrawal_permission(self) -> bool:
        return 'withdraw-funds' in await self.permissions()

    async def validate_permissions(self):
        permissions = await self.permissions()
        required = {'query-funds', 'query-open-trades', 'query-closed-trades', 'modify-trades', 'close-trades'}
        if 'withdraw-funds' in permissions:
            raise ValueError('Use a Kraken key without withdrawal permission')
        if not required.issubset(permissions):
            raise ValueError('Kraken key needs balance, open/closed order query, modify and cancel permissions')

    def minimum_viable_quantity(self, symbol: str, price: float) -> float:
        market = self.client.market(symbol)
        if not isinstance(market, dict):
            return 0.0
        price = float(price)
        limits = market.get('limits') or {}
        amount_min = limits.get('amount', {}).get('min')
        cost_min = limits.get('cost', {}).get('min')
        minimum = 0.0
        if amount_min is not None:
            minimum = max(minimum, float(amount_min))
        if cost_min is not None and price > 0:
            minimum = max(minimum, float(cost_min) / price)
        return minimum

    async def prepare_order(self, symbol, quantity, price):
        if not all(math.isfinite(v) and v > 0 for v in (quantity, price)):
            raise ValueError('Order quantity and price must be finite and positive')
        await self.client.load_markets()
        market = self.client.market(symbol)
        if not market.get('spot') or market.get('active') is False or market['quote'] != 'EUR':
            raise ValueError('Only active EUR spot pairs are supported')
        minimum_viable = self.minimum_viable_quantity(symbol, price)
        if minimum_viable and quantity < minimum_viable:
            raise ValueError('Order is below exchange minimum size')
        quantity = float(self.client.amount_to_precision(symbol, quantity))
        price = float(self.client.price_to_precision(symbol, price))
        for field, value in [('amount', quantity), ('cost', quantity * price)]:
            bounds = market.get('limits', {}).get(field, {})
            if value <= 0 or (bounds.get('min') is not None and value < bounds['min']):
                raise ValueError('Order is below exchange minimum size')
            if bounds.get('max') is not None and value > bounds['max']:
                raise ValueError('Order exceeds exchange maximum size')
        return quantity, price

    async def trading_fee(self, symbol):
        """Use documented TradeVolume fields, without legacy CCXT fee-info."""
        await self.client.load_markets()
        market=self.client.market(symbol)
        try:
            response=await self.client.request('TradeVolume','private','POST',{'pair':market['id']})
        except ccxt.ExchangeError as exc:
            reason='EGeneral:Invalid arguments' if 'EGeneral:Invalid arguments' in str(exc) else type(exc).__name__
            transient=isinstance(exc, (ccxt.InvalidNonce, ccxt.RateLimitExceeded,
                ccxt.DDoSProtection, ccxt.NetworkError))
            raise KrakenPreflightError(
                f'Kraken TradeVolume fee check failed for {symbol} ({reason}); no buy order was submitted.',
                retryable=transient) from exc
        result=response.get('result') or {}
        fees=result.get('fees') or {}
        row=fees.get(market['id']) or fees.get((market.get('info') or {}).get('altname')) or {}
        try:
            taker=float(row['fee'])/100
        except (KeyError,TypeError,ValueError):
            raise ValueError(f'Kraken TradeVolume returned no usable fee for {symbol}; no buy order was submitted.')
        if not math.isfinite(taker) or not 0 <= taker < 1 or response.get('error'):
            raise ValueError(f'Kraken TradeVolume returned an invalid fee for {symbol}; no buy order was submitted.')
        return {'taker':taker}

    async def get_order_book(self, symbol):
        return await self.client.fetch_order_book(symbol, limit=100)

    async def open_orders(self):
        return await self.client.fetch_open_orders()

    async def find_order(self, client_id, symbol):
        # IDs identify OPEN orders only; never resubmit after an ambiguous response.
        orders = await self.client.fetch_open_orders(symbol, params={'cl_ord_id':client_id})
        orders += await self.client.fetch_closed_orders(symbol, params={'cl_ord_id':client_id})
        matches = [o for o in orders if o.get('info', {}).get('cl_ord_id') == client_id]
        if len(matches) > 1:
            raise ValueError('Multiple exchange orders match one client ID')
        return self._order_to_result(matches[0]) if matches else None

    def _kraken_error_list(self, response):
        if isinstance(response, dict):
            errors = response.get('error', [])
            if isinstance(errors, list):
                return errors
            if errors:
                return [str(errors)]
            return []
        if isinstance(response, list):
            return response
        return [str(response)]

    def _kraken_retryable(self, message: str) -> bool:
        normalized = str(message).lower()
        if 'market preflight unavailable' in normalized:
            return True
        retry_markers = (
            'rate limit', 'too many requests', 'temporary lockout', 'temporarily unavailable',
            'timeout', 'network error', 'eapi:rate limit exceeded', 'eorder:rate limit exceeded',
        )
        return any(marker in normalized for marker in retry_markers)

    async def _kraken_order_diagnostic(self, symbol, side, quantity, price, client_id, request):
        pair = self.client.market(symbol)
        market_info = pair if isinstance(pair, dict) else {}
        estimated_notional = float(quantity) * float(price) if price is not None and quantity is not None else None
        return {
            'pair': symbol,
            'kraken_pair': market_info.get('id'),
            'side': side.value if hasattr(side, 'value') else str(side),
            'order_type': request.get('ordertype'),
            'volume': request.get('volume'),
            'price': request.get('price'),
            'leverage': request.get('leverage'),
            'viqc': request.get('viqc'),
            'oflags': request.get('oflags'),
            'time_in_force': request.get('timeinforce'),
            'validate': request.get('validate'),
            'client_order_id': client_id,
            'estimated_notional': estimated_notional,
            'pair_status': market_info.get('active'),
            'best_bid': None,
            'best_ask': None,
            'quote_currency': market_info.get('quote'),
            'base_currency': market_info.get('base'),
        }

    async def submit_ioc(self, symbol, side, quantity, price, client_id):
        # CCXT 4.3.50 drops oflags for non-post-only limit orders. Build the
        # documented request explicitly while retaining CCXT signing/error handling.
        quantity, price = await self.prepare_order(symbol, quantity, price)
        market = self.client.market(symbol)
        request = {'pair': market['id'], 'type': side.value.lower(), 'ordertype': 'limit',
                   'volume': self.client.amount_to_precision(symbol, quantity),
                   'price': self.client.price_to_precision(symbol, price),
                   'cl_ord_id': client_id, 'timeinforce': 'IOC', 'oflags': 'fciq'}
        diagnostic = await self._kraken_order_diagnostic(symbol, side, quantity, price, client_id, request)
        logger.warning('kraken_order_attempt', extra={'kraken_order_attempt': diagnostic})
        last_error = None
        for attempt in range(1, 4):
            try:
                response = await self.client.request('AddOrder', 'private', 'POST', request)
                errors = self._kraken_error_list(response)
                if errors:
                    last_error = errors
                    message = ' '.join(str(item) for item in errors)
                    retryable = self._kraken_retryable(message)
                    if retryable and attempt < 3:
                        existing = await self.find_order(client_id, symbol)
                        if existing is not None and existing.order_id:
                            logger.warning('kraken_duplicate_order_detected', extra={'kraken_order_attempt': diagnostic, 'client_order_id': client_id, 'existing_order_id': existing.order_id})
                            return existing
                        await self._sleep(0.5 * attempt + random.uniform(0.1, 0.5))
                        continue
                    if 'EGeneral:Invalid arguments' in message or 'EOrder:Invalid order' in message:
                        raise OrderRejected(f'Kraken AddOrder rejected {symbol}: {message}. Check pair, volume, price precision and order options; no automatic retry was sent.')
                    raise ValueError(f'Kraken AddOrder rejected {symbol}: {message}')
                ids = (response.get('result') or {}).get('txid')
                if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str) or not ids[0]:
                    raise ValueError('Kraken AddOrder response did not confirm one order ID; reconcile before retrying')
                logger.info('kraken_order_submitted', extra={'kraken_order_attempt': diagnostic, 'kraken_error': []})
                return OrderResult(ids[0], OrderStatus.PENDING, 0., 0., 0.)
            except Exception as exc:
                last_error = self._kraken_error_list(exc)
                message = str(exc)
                retryable = self._kraken_retryable(message)
                if retryable and attempt < 3:
                    existing = await self.find_order(client_id, symbol)
                    if existing is not None and existing.order_id:
                        logger.warning('kraken_duplicate_order_detected', extra={'kraken_order_attempt': diagnostic, 'client_order_id': client_id, 'existing_order_id': existing.order_id})
                        return existing
                    logger.warning('kraken_order_retry', extra={'kraken_order_attempt': diagnostic, 'attempt_number': attempt, 'kraken_error': last_error, 'retryable': True})
                    await self._sleep(0.5 * attempt + random.uniform(0.1, 0.5))
                    continue
                logger.error('kraken_order_failed', extra={'kraken_order_attempt': diagnostic, 'attempt_number': attempt, 'kraken_error': last_error})
                if isinstance(exc, ccxt.BadRequest) and 'EGeneral:Invalid arguments' in message:
                    raise OrderRejected(f'Kraken AddOrder rejected {symbol}: {message}. Check pair, volume, price precision and order options; no automatic retry was sent.') from exc
                if isinstance(exc, ccxt.InvalidOrder):
                    if 'market preflight unavailable' in message.lower():
                        raise OrderRejected(f'Kraken AddOrder rejected {symbol}: {message}; order was not accepted by Kraken and was not retried after the retry budget was exhausted.') from exc
                raise
        raise ValueError(f'Kraken market order failed after 3 attempts: {last_error}')

    def _order_to_result(self, order):
        status_map = {'open':OrderStatus.PENDING, 'closed':OrderStatus.FILLED,
                      'canceled':OrderStatus.CANCELED, 'expired':OrderStatus.CANCELED,
                      'rejected':OrderStatus.REJECTED}
        quantity = float(order.get('filled') or 0)
        average = float(order.get('average') or order.get('price') or 0)
        cost = order.get('cost')
        fees = order.get('fees') or ([order['fee']] if order.get('fee') else [])
        base, quote = (order.get('symbol') or '').split('/') if '/' in (order.get('symbol') or '') else ('', 'EUR')
        quote_fee = base_fee = 0.
        for fee in fees:
            amount = float(fee.get('cost') or 0)
            if fee.get('currency') == base: base_fee += amount
            elif fee.get('currency') == quote or not amount: quote_fee += amount
            else: raise ValueError('Unsupported or missing fee currency; reconciliation required')
        if quantity and not fees:
            raise ValueError('Exchange fill has no fee information; reconciliation required')
        return OrderResult(order_id=order.get('id'),status=status_map.get(order.get('status'),OrderStatus.PENDING),
                           filled_qty=quantity,avg_price=average,fee=quote_fee,raw_response=None,
                           cost=float(cost) if cost is not None else quantity*average,base_fee=base_fee)
