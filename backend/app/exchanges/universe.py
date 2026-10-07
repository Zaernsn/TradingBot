"""Core pairs and historical research symbols; live memes are discovered from Kraken."""
CURATED_PAIRS = ['BTC/EUR', 'ETH/EUR', 'SOL/EUR', 'XRP/EUR', 'ADA/EUR']
# Historical research/import defaults only; not the live discovery allowlist.
WATCHLIST_LIMIT = 30
MEMECOIN_WATCHLIST_TARGET = 30
MEMECOIN_PAIRS = [
    'DOGE/EUR', 'SHIB/EUR', 'PEPE/EUR', 'BONK/EUR', 'WIF/EUR',
    'FLOKI/EUR', 'POPCAT/EUR', 'BRETT/EUR', 'MOG/EUR', 'MEW/EUR',
    'BOME/EUR', 'SNEK/EUR', 'TURBO/EUR', 'NEIRO/EUR', 'PNUT/EUR',
    'GOAT/EUR', 'ACT/EUR', 'FARTCOIN/EUR', 'TRUMP/EUR', 'MELANIA/EUR',
    'SPX/EUR', 'PONKE/EUR', 'MEME/EUR', 'DEGEN/EUR', 'GIGA/EUR',
    'FWOG/EUR', 'MOODENG/EUR', 'PENGU/EUR', 'CHEEMS/EUR', 'SAMO/EUR',
]
SUPPORTED_PAIRS = CURATED_PAIRS + MEMECOIN_PAIRS


def is_memecoin(symbol):
    """Conservatively apply meme caps to discovered non-core EUR spot pairs.

    Runtime entries are sourced only from Kraken's meme category intersection.
    This classification remains valid across restarts and category removals.
    """
    return isinstance(symbol, str) and symbol.endswith('/EUR') and symbol not in CURATED_PAIRS
