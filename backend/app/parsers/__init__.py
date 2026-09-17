"""Registry mapping a platform family onto its table and parse function.

To add a platform: add the package name in platforms.py, add a model in
models.py, then register the pair here.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..models import DouyinPost, TikTokPost, YouTubePost
from . import douyin, tiktok, youtube

PLATFORM_TABLES: dict[str, tuple[type, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "douyin": (DouyinPost, douyin.structure),
    "tiktok": (TikTokPost, tiktok.structure),
    "youtube": (YouTubePost, youtube.structure),
}

__all__ = ["PLATFORM_TABLES", "base", "douyin", "tiktok", "youtube"]

from . import base  # noqa: E402  (re-exported for convenience)
