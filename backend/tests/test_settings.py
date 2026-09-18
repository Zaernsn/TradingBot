import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import create_application
from app.db.base import Base
from app.db.session import get_db

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def client():
    Base.metadata.create_all(bind=engine)
    app = create_application()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


def _auth_header(client, email, password):
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_save_and_get_exchange_status(client):
    headers = _auth_header(client, "u@example.com", "pass")
    res = client.post("/api/v1/settings/exchange", json={"api_key": "key12345", "api_secret": "secret12345"}, headers=headers)
    assert res.status_code == 200
    res = client.get("/api/v1/settings/exchange", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is True
    assert body["masked_key"].endswith("2345")
