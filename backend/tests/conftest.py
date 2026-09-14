"""Test fixtures.

Environment is set before any app module is imported, because config
is read once at import time.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="scraper-tests-"))
_APPROVED = _TMP / "approved.csv"
_APPROVED.write_text(
    "email,participant_id,note\n"
    "p1@example.edu,P001,pilot\n"
    "p2@example.edu,P002,pilot\n",
    encoding="utf-8",
)

os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["APPROVED_PARTICIPANTS_CSV"] = str(_APPROVED)
os.environ["PAIRING_WINDOW_SECONDS"] = "900"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def api_key(client: TestClient) -> str:
    response = client.post(
        "/api/auth/register",
        json={"email": "p1@example.edu", "device_id": "pixel-7a"},
    )
    assert response.status_code == 200
    return response.json()["api_key"]
