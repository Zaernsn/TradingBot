from datetime import datetime, timezone
from app.ml.features import build_features
from app.exchanges.base import OHLCV


def make_candles(n=50):
    candles = []
    price = 50000.0
    for i in range(n):
        candles.append(
            OHLCV(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1.0,
            )
        )
        price *= 1.001
    return candles


def test_build_features_shape():
    candles = make_candles(60)
    df = build_features(candles)
    assert "rsi" in df.columns
    assert "macd" in df.columns
    assert len(df) > 0
