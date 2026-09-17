"""HTTP API for the capture backend."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import participants as participant_registry
from .auth import require_participant
from .dashboard import require_admin_view, router as dashboard_router
from .db import get_session, init_db
from .links import canonical_url_for, extract
from .models import CaptureEvent, Participant, SharedLink
from .pairing import pair_shared_link
from .parsers import PLATFORM_TABLES, base
from .platforms import family_for_platform, platform_for_package
from .views import publication
from .schemas import (
    BatchResponse,
    CaptureBatch,
    RegisterRequest,
    RegisterResponse,
    SharedLinkIn,
    SharedLinkResponse,
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Douyin/TikTok capture backend", version="0.1.0", lifespan=lifespan
)
app.include_router(dashboard_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=RegisterResponse)
def register(
    body: RegisterRequest, session: Session = Depends(get_session)
) -> RegisterResponse:
    participant = participant_registry.register(session, body.email)
    if participant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="email is not on the approved participant list",
        )
    return RegisterResponse(
        participant_id=participant.participant_id, api_key=participant.api_key
    )


@app.post("/api/captures/batch", response_model=BatchResponse)
def ingest_batch(
    body: CaptureBatch,
    participant: Participant = Depends(require_participant),
    session: Session = Depends(get_session),
) -> BatchResponse:
    accepted = duplicates = rejected = 0

    for item in body.captures:
        platform = platform_for_package(item.platform_package)
        family = family_for_platform(platform) if platform else None
        if platform is None or family not in PLATFORM_TABLES:
            rejected += 1
            continue

        captured_at = base.parse_captured_at(item.captured_at) or datetime.now(
            timezone.utc
        ).replace(tzinfo=None)

        event = CaptureEvent(
            participant_id=participant.participant_id,
            device_id=body.device_id,
            platform=platform,
            fingerprint=item.fingerprint,
            capture_date=captured_at.date().isoformat(),
            captured_at=captured_at,
            payload=json.dumps(item.payload, ensure_ascii=False),
        )
        session.add(event)
        try:
            session.commit()
        except IntegrityError:
            # Same post, same participant, same day -- already recorded.
            session.rollback()
            duplicates += 1
            continue

        model, structure = PLATFORM_TABLES[family]
        row = structure(item.payload)
        # "11h ago" is exact once the capture time is known, so the
        # reference has to come from here rather than from the parser.
        row["posted_on"] = base.resolve_posted_on(
            item.payload.get("posted_at_raw"), reference=captured_at
        )
        # An id read off the screen is already a complete answer; no
        # share, no pairing, and no interaction with the app.
        if row.get("video_id"):
            row["video_url"] = canonical_url_for(
                family, row["video_id"], row.get("author_handle")
            )
        session.add(
            model(
                capture_event_id=event.id,
                participant_id=participant.participant_id,
                captured_at=captured_at,
                **row,
            )
        )
        session.commit()
        accepted += 1

    return BatchResponse(accepted=accepted, duplicates=duplicates, rejected=rejected)


@app.post("/api/links/shared", response_model=SharedLinkResponse)
def ingest_shared_link(
    body: SharedLinkIn,
    participant: Participant = Depends(require_participant),
    session: Session = Depends(get_session),
) -> SharedLinkResponse:
    parsed = extract(body.raw_text)
    if parsed.platform is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="no Douyin or TikTok link found in the shared text",
        )

    shared_at = base.parse_captured_at(body.shared_at) or datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    link = SharedLink(
        participant_id=participant.participant_id,
        platform=parsed.platform,
        raw_text=body.raw_text,
        video_id=parsed.video_id,
        author_handle=parsed.author_handle,
        canonical_url=parsed.canonical_url,
        shared_at=shared_at,
        fingerprint=body.fingerprint,
    )
    session.add(link)
    session.commit()

    paired = pair_shared_link(session, link)

    return SharedLinkResponse(
        stored=True,
        platform=parsed.platform,
        video_id=parsed.video_id,
        canonical_url=parsed.canonical_url,
        needs_resolution=parsed.needs_resolution,
        paired_post_id=paired,
    )


_EXPORT_COLUMNS = [
    "id",
    "participant_id",
    "captured_at",
    "author_handle",
    "author_name",
    "caption",
    "posted_at_raw",
    "posted_on",
    "music",
    "feed",
    "like_count",
    "comment_count",
    "share_count",
    "save_count",
    "counts_approximate",
    "is_ad",
    "is_ai_generated",
    "video_id",
    "video_url",
]

#: Derived on the way out rather than stored. `video_id` is the fact;
#: these are a pure function of it, so there is no second copy to drift
#: and nothing to migrate. See app/snowflake.py for the decoding and
#: its per-platform confidence.
_DERIVED_COLUMNS = ["posted_at_exact", "posted_at_source"]


@app.get("/api/export/posts.csv", dependencies=[Depends(require_admin_view)])
def export_posts(
    platform: str = Query(description="douyin or tiktok"),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    family = family_for_platform(platform) or platform
    registered = PLATFORM_TABLES.get(family)
    if registered is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown platform {platform}"
        )
    model, _ = registered

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_EXPORT_COLUMNS + _DERIVED_COLUMNS)
    for post in session.scalars(select(model).order_by(model.captured_at)):
        exact, _, source = publication(post.video_id, post.posted_on, post.posted_at_raw)
        writer.writerow(
            [getattr(post, column) for column in _EXPORT_COLUMNS]
            + [exact.isoformat() if exact else "", source]
        )

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{family}_posts.csv"'
        },
    )
