"""Read-only Kraken authentication check. No orders, balances, or secrets printed.

From the project root:
  backend/.venv/Scripts/python backend/scripts/kraken_smoke.py
  backend/.venv/Scripts/python backend/scripts/kraken_smoke.py --authenticate

After a temporary lockout, pause API requests for 15 minutes before authenticating.
"""
import argparse
import asyncio
import base64
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
import ccxt.async_support as ccxt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.preflight_errors import preflight_error, preflight_reason


async def run(env_file, authenticate=False):
    if not env_file.is_file():
        print('FAIL: env file does not exist.')
        return 1
    values = dotenv_values(env_file)
    credentials = {}
    for name in ('KRAKEN_API_KEY', 'KRAKEN_API_SECRET'):
        # Same precedence as application settings: process environment wins.
        value = os.environ.get(name, values.get(name))
        source = 'process environment' if name in os.environ else 'env file'
        if not value or value != value.strip():
            print(f'FAIL: {name} missing or contains surrounding whitespace ({source}).')
            return 1
        credentials[name] = value
        print(f'{name}: present ({source}); value hidden.')
    try:
        base64.b64decode(credentials['KRAKEN_API_SECRET'], validate=True)
    except (ValueError, base64.binascii.Error):
        print('FAIL: API secret is not valid base64.')
        return 1
    if not authenticate:
        print('Local format checks passed; authentication has NOT been tested. Use --authenticate for one read-only request.')
        return 0
    client = ccxt.kraken({'apiKey': credentials['KRAKEN_API_KEY'],
                          'secret': credentials['KRAKEN_API_SECRET'],
                          'enableRateLimit': True, 'timeout': 15000,
                          'maxRetriesOnFailure': 0})
    try:
        # Direct request avoids market-loading calls and never places an order.
        response = await client.request('GetApiKeyInfo', 'private', 'POST', {})
        permissions = response.get('result', {}).get('permissions')
        if not isinstance(permissions, list):
            print('FAIL: unexpected API key information response; payload hidden.')
            return 1
        print('PASS: Kraken authenticated the configured key and secret.')
        required = {'query-funds', 'query-open-trades', 'query-closed-trades', 'modify-trades', 'close-trades'}
        missing = required - set(permissions)
        print('Live permissions: ' + ('missing ' + ', '.join(sorted(missing)) if missing else 'all required permissions present'))
        print('Withdrawal permission: ' + ('ENABLED (app rejects live activation)' if 'withdraw-funds' in permissions else 'disabled'))
        return 0
    except Exception as exc:
        print(f'FAIL: category={type(exc).__name__} reason={preflight_reason(exc)}')
        print(preflight_error(exc))
        print('Authentication could not be confirmed. No retry was attempted.')
        return 1
    finally:
        await client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path(__file__).resolve().parents[2] / '.env')
    parser.add_argument('--authenticate', action='store_true')
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.env_file, args.authenticate)))
