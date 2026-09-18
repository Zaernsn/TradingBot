from fastapi.testclient import TestClient
from app.main import create_application


def test_get_pairs():
    app = create_application()
    with TestClient(app) as client:
        res = client.get("/api/v1/market/pairs")
    assert res.status_code == 200
    assert "BTC/EUR" in res.json()
