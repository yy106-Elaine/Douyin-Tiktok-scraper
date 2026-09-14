"""API-key authentication.

Two kinds of key are accepted: the single admin key from the
environment (used for exports and operational endpoints) and the
per-participant keys handed out at registration (used for ingest).
"""
from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import Participant


def _unauthorised() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API key"
    )


def is_admin_key(key: str) -> bool:
    configured = settings.admin_api_key
    if not configured:
        return False
    return hmac.compare_digest(key, configured)


def require_participant(
    x_api_key: str = Header(default=""),
    session: Session = Depends(get_session),
) -> Participant:
    if not x_api_key:
        raise _unauthorised()
    participant = session.scalar(
        select(Participant).where(Participant.api_key == x_api_key)
    )
    if participant is None:
        raise _unauthorised()
    return participant


def require_admin(x_api_key: str = Header(default="")) -> None:
    if not x_api_key or not is_admin_key(x_api_key):
        raise _unauthorised()
