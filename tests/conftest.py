"""Shared test setup."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_supervisor(monkeypatch):
    """Tests never reach a real Supervisor (notifications, events, reloads), even when run on a
    Home Assistant host; a test that checks those calls sets a token and mocks the transport."""
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
