"""Refresh meme membership from Kraken's public category page (not a user list)."""
from html.parser import HTMLParser
import asyncio
import re
import time
import httpx

CATEGORY_URL = 'https://www.kraken.com/categories/meme'
_cached = set()
_cached_at = 0.
_lock = asyncio.Lock()


class MemeCategoryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.symbols = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href', '').startswith('/prices/'):
            # Kraken puts the canonical ticker on each category asset link.
            for token in attrs.get('class', '').split():
                if re.fullmatch(r'[A-Z0-9]{2,20}', token):
                    self.symbols.add(token)


async def meme_symbols():
    global _cached, _cached_at
    async with _lock:
        if _cached and time.monotonic() - _cached_at < 300:
            return set(_cached)
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(CATEGORY_URL)
            response.raise_for_status()
        parser = MemeCategoryParser()
        parser.feed(response.text)
        if len(parser.symbols) < 5:
            raise ValueError('Kraken meme category unavailable or its format changed')
        _cached = parser.symbols
        _cached_at = time.monotonic()
        return set(_cached)
