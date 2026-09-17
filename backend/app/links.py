"""Extract and canonicalise video links out of shared text.

Share sheets do not hand over a bare URL. Douyin's clipboard payload is
a paragraph of Chinese marketing copy with a short link buried in it;
TikTok's is usually a caption followed by a full or short URL. Both
short-link forms are opaque and only resolve to a video id via an HTTP
redirect, which we do lazily and explicitly rather than in the ingest
path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_URL = re.compile(r"https?://[^\s<>一-鿿]+", re.IGNORECASE)

_TIKTOK_FULL = re.compile(
    r"tiktok\.com/@(?P<handle>[\w.\-]+)/video/(?P<vid>\d+)", re.IGNORECASE
)
#: Three short forms are in circulation. `/t/<slug>` is what the app's
#: own "copy link" produces today; vm./vt. are older and still appear in
#: pasted text.
_TIKTOK_SHORT = re.compile(
    r"(?:(?:vm|vt)\.tiktok\.com|(?:www\.)?tiktok\.com/t)/(?P<slug>[\w]+)",
    re.IGNORECASE,
)
_DOUYIN_FULL = re.compile(r"douyin\.com/video/(?P<vid>\d+)", re.IGNORECASE)
_DOUYIN_SHORT = re.compile(r"v\.douyin\.com/(?P<slug>[\w\-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class ExtractedLink:
    platform: str | None
    video_id: str | None
    author_handle: str | None
    canonical_url: str | None
    raw_url: str | None
    #: True when the link is a short form that still needs an HTTP
    #: redirect before a video id is known.
    needs_resolution: bool


def _first_url(text: str) -> str | None:
    match = _URL.search(text or "")
    if not match:
        return None
    # Share text often runs punctuation straight into the URL.
    return match.group(0).rstrip(".,;)】]｝》")


def extract(text: str) -> ExtractedLink:
    """Pull whatever identity we can out of a shared blob of text."""
    raw_url = _first_url(text)
    haystack = text or ""

    if m := _TIKTOK_FULL.search(haystack):
        vid = m.group("vid")
        handle = m.group("handle")
        return ExtractedLink(
            platform="tiktok",
            video_id=vid,
            author_handle=handle,
            canonical_url=f"https://www.tiktok.com/@{handle}/video/{vid}",
            raw_url=raw_url,
            needs_resolution=False,
        )

    if m := _DOUYIN_FULL.search(haystack):
        vid = m.group("vid")
        return ExtractedLink(
            platform="douyin",
            video_id=vid,
            author_handle=None,
            canonical_url=f"https://www.douyin.com/video/{vid}",
            raw_url=raw_url,
            needs_resolution=False,
        )

    if m := _TIKTOK_SHORT.search(haystack):
        return ExtractedLink(
            platform="tiktok",
            video_id=None,
            author_handle=None,
            canonical_url=None,
            raw_url=raw_url or f"https://www.tiktok.com/t/{m.group('slug')}/",
            needs_resolution=True,
        )

    if m := _DOUYIN_SHORT.search(haystack):
        return ExtractedLink(
            platform="douyin",
            video_id=None,
            author_handle=None,
            canonical_url=None,
            raw_url=raw_url or f"https://v.douyin.com/{m.group('slug')}",
            needs_resolution=True,
        )

    return ExtractedLink(
        platform=None,
        video_id=None,
        author_handle=None,
        canonical_url=None,
        raw_url=raw_url,
        needs_resolution=raw_url is not None,
    )


def canonical_url_for(platform: str, video_id: str, handle: str | None = None) -> str:
    """Build the public web URL for a known video id."""
    if platform.startswith("youtube"):
        return f"https://www.youtube.com/watch?v={video_id}"
    if platform.startswith("tiktok"):
        return f"https://www.tiktok.com/@{handle or 'i'}/video/{video_id}"
    return f"https://www.douyin.com/video/{video_id}"
