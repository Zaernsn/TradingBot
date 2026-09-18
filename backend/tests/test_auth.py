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


def test_register_and_login_json(client):
    client.post("/api/v1/auth/register", json={"email": "test@example.com", "password": "secret"})
    res = client.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "secret"})
    assert res.status_code == 200
    assert "access_token" in res.json()


def test_register_and_login_form(client):
    client.post("/api/v1/auth/register", json={"email": "test@example.com", "password": "secret"})
    res = client.post(
        "/api/v1/auth/login",
        data={"username": "test@example.com", "password": "secret"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res.status_code == 200
    assert "access_token" in res.json()


def test_login_wrong_password_json(client):
    client.post("/api/v1/auth/register", json={"email": "test@example.com", "password": "secret"})
    res = client.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "wrong"})
    assert res.status_code == 401
