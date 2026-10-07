import ccxt
import pytest
from sqlalchemy.exc import OperationalError
from app.services.preflight_errors import preflight_error, preflight_reason, retryable_preflight_error


@pytest.mark.parametrize('exc,expected', [
    (ccxt.AuthenticationError('secret-payload'), 'authentication'),
    (ccxt.PermissionDenied('secret-payload'), 'permissions'),
    (ccxt.InvalidNonce('secret-payload'), 'nonce'),
    (ccxt.RateLimitExceeded('secret-payload'), 'rate-limited'),
    (ccxt.RequestTimeout('secret-payload'), 'connection'),
    (ccxt.DDoSProtection('secret-payload EGeneral:Temporary lockout'), '15 minutes'),
    (ccxt.DDoSProtection('secret-payload EGeneral:Too many requests'), 'throttling'),
    (ccxt.DDoSProtection('secret-payload'), 'protection'),
    (OperationalError('secret-payload', {}, Exception()), 'database'),
    (RuntimeError('secret-payload'), 'unexpected'),
])
def test_safe_diagnostic(exc, expected):
    message = preflight_error(exc)
    assert expected in message
    assert 'secret-payload' not in message


def test_reason_only_exposes_allowlisted_code():
    assert preflight_reason(ccxt.DDoSProtection('secret-payload EGeneral:Temporary lockout')) == 'EGeneral:Temporary lockout'
    assert preflight_reason(ccxt.DDoSProtection('secret-payload')) == 'unspecified'
    assert preflight_reason(RuntimeError('secret-payload EGeneral:Temporary lockout')) == 'unspecified'


@pytest.mark.parametrize('exc', [
    ccxt.InvalidNonce('nonce'), ccxt.RateLimitExceeded('rate'),
    ccxt.RequestTimeout('timeout'), TimeoutError('timeout'),
])
def test_transient_preflight_errors_are_retryable(exc):
    assert retryable_preflight_error(exc)


@pytest.mark.parametrize('exc', [
    ccxt.AuthenticationError('auth'), ccxt.PermissionDenied('permission'),
    ValueError('risk control'),
])
def test_terminal_preflight_errors_are_not_retryable(exc):
    assert not retryable_preflight_error(exc)
