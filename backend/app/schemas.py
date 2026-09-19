"""Request/response models for the HTTP API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    device_id: str = Field(min_length=1, max_length=128)


class RegisterResponse(BaseModel):
    participant_id: str
    api_key: str


class CaptureIn(BaseModel):
    """One finalised observation, as emitted by the on-device buffer."""

    platform_package: str = Field(min_length=1, max_length=128)
    fingerprint: str = Field(min_length=1, max_length=255)
    captured_at: Any
    payload: dict[str, Any] = Field(default_factory=dict)


class CaptureBatch(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    captures: list[CaptureIn] = Field(max_length=200)


class BatchResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: int


class SharedLinkIn(BaseModel):
    """Raw text handed over by the Android share sheet."""

    raw_text: str = Field(min_length=1)
    shared_at: Any = None

    #: Set when the device harvested this link for a post it had just
    #: captured. Pairing is then exact rather than a time-window guess.
    fingerprint: str | None = Field(default=None, max_length=255)


class SharedLinkResponse(BaseModel):
    stored: bool
    platform: str | None
    video_id: str | None
    canonical_url: str | None
    needs_resolution: bool
    paired_post_id: int | None


class AuthorIdentityIn(BaseModel):
    """An account's stable id, read off its profile page."""

    platform: str = Field(min_length=1, max_length=32)
    #: The display name the feed shows, which is how stored rows are
    #: found again.
    author_name: str = Field(min_length=1, max_length=255)
    #: The 抖音号.
    author_handle: str = Field(min_length=1, max_length=255)


class AuthorIdentityBatchIn(BaseModel):
    identities: list[AuthorIdentityIn] = Field(default_factory=list, max_length=200)


class AuthorIdentityBatchResponse(BaseModel):
    accepted: int
    rows_filled: int
