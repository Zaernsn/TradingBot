from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import create_application
from app.exchanges.base import Ticker


def test_get_pairs():
    app = create_application()
    with TestClient(app) as client:
        res = client.get("/api/v1/market/pairs")
    assert res.status_code == 200
    assert "BTC/EUR" in res.json()


def test_get_price_with_slash_symbol(monkeypatch):
    async def mock_ticker(self, symbol):
        return Ticker(symbol=symbol, bid=1.0, ask=1.0, last=1.0, volume=1.0, timestamp=datetime.now(timezone.utc))

    monkeypatch.setattr("app.exchanges.paper.PaperExchange.get_ticker", mock_ticker)
    app = create_application()
    with TestClient(app) as client:
        res = client.get("/api/v1/market/price/ADA/EUR")
    assert res.status_code == 200
    assert res.json()["symbol"] == "ADA/EUR"
