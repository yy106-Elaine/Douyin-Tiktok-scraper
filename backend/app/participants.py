"""Participant whitelist and registration.

Only emails listed in the approved-participants CSV may register. The
CSV is read on every call so the list can be edited without a restart.
"""
from __future__ import annotations

import csv
import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Participant


def approved_emails() -> dict[str, str]:
    """email -> participant_id, from the approved-participants CSV."""
    path = Path(settings.approved_participants_csv)
    if not path.exists():
        return {}

    approved: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            email = (row.get("email") or "").strip().lower()
            if not email:
                continue
            approved[email] = (row.get("participant_id") or "").strip() or email
    return approved


def register(session: Session, email: str) -> Participant | None:
    """Register an approved email, or return None when not on the list.

    Re-registering an existing participant returns the existing record
    so that reinstalling the app does not orphan earlier captures.
    """
    normalised = email.strip().lower()
    approved = approved_emails()
    if normalised not in approved:
        return None

    existing = session.scalar(
        select(Participant).where(Participant.email == normalised)
    )
    if existing is not None:
        return existing

    participant = Participant(
        email=normalised,
        participant_id=approved[normalised],
        api_key=secrets.token_urlsafe(32),
    )
    session.add(participant)
    session.commit()
    return participant
