"""HTTP tests must not restore running bots from the developer database."""
from unittest.mock import AsyncMock
import pytest


@pytest.fixture(autouse=True)
def isolate_scheduler_startup(monkeypatch):
    monkeypatch.setattr('app.services.bot_service.BotOrchestrator.restore', AsyncMock())
