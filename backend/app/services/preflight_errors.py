"""Actionable preflight errors without leaking exchange responses or credentials."""
import asyncio
import ccxt
from sqlalchemy.exc import SQLAlchemyError
from cryptography.fernet import InvalidToken


def retryable_preflight_error(exc):
    """True only when no business-rule change can fix the transient failure."""
    if getattr(exc, 'retryable', False):
        return True
    return isinstance(exc, (
        ccxt.InvalidNonce, ccxt.RateLimitExceeded, ccxt.DDoSProtection,
        ccxt.NetworkError, asyncio.TimeoutError, TimeoutError, ConnectionError,
    ))


def retry_delay_seconds(exc, attempt):
    """Bound retries so a sick exchange is not polled every bot cycle."""
    if isinstance(exc, ccxt.DDoSProtection) and preflight_reason(exc) == 'EGeneral:Temporary lockout':
        return 15 * 60
    if isinstance(exc, (ccxt.RateLimitExceeded, ccxt.DDoSProtection)):
        return 2 * 60
    return min(5 * 60, 30 * (2 ** max(0, attempt - 1)))


def preflight_reason(exc):
    """Return only recognized public error codes, never exchange payloads."""
    if isinstance(exc, ccxt.DDoSProtection):
        for code in ('EGeneral:Temporary lockout', 'EGeneral:Too many requests',
                     'EAPI:Rate limit exceeded', 'EOrder:Rate limit exceeded'):
            if code in str(exc):
                return code
    return 'unspecified'


def preflight_error(exc):
    if isinstance(exc, InvalidToken):
        return 'Saved Kraken credentials cannot be decrypted. Restore the encryption key used when they were saved.'
    if isinstance(exc, ccxt.InvalidNonce):
        return 'Kraken rejected the request nonce. Check the server clock and whether another app is using the same API key.'
    if isinstance(exc, ccxt.PermissionDenied):
        return 'Kraken denied API access. Check the key permissions and any IP restrictions.'
    if isinstance(exc, ccxt.AuthenticationError):
        return 'Kraken rejected API authentication. Check the saved key and secret, key expiry, IP restrictions and API-key 2FA settings.'
    if isinstance(exc, ccxt.RateLimitExceeded):
        return 'Kraken rate-limited the preflight requests. Wait briefly before trying again.'
    if isinstance(exc, ccxt.DDoSProtection):
        reason = preflight_reason(exc)
        if reason == 'EGeneral:Temporary lockout':
            return 'Kraken temporarily locked API access after repeated failed requests. Pause API requests for 15 minutes before retrying, then check for invalid signatures or nonce conflicts if it recurs.'
        if reason != 'unspecified':
            return 'Kraken rejected requests due to throttling. Reduce API polling and wait before retrying live preflight.'
        return 'Kraken returned a protection or throttling rejection. The response did not identify a recognized Kraken error code. Avoid repeated retries and check backend network access to Kraken.'
    if isinstance(exc, ccxt.NetworkError):
        return 'The backend could not complete its connection to Kraken. Check network access and retry when Kraken is reachable.'
    if isinstance(exc, SQLAlchemyError):
        return 'The local database failed during live preflight. Apply pending database migrations and check backend database logs.'
    if isinstance(exc, ccxt.ExchangeError):
        return 'Kraken rejected a preflight API request. Check the key permissions, account restrictions and backend diagnostic category.'
    return 'An unexpected backend error interrupted live preflight. Check the backend diagnostic category.'
