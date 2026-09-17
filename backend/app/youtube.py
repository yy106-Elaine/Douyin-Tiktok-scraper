"""Collect YouTube through its Data API, and re-check the same way.

This platform is different in kind from the other two and the
difference is worth naming, because it changes what the data means.

Douyin and TikTok are read off a phone screen: a person scrolls, an
accessibility service sees what was rendered, counts arrive
abbreviated, publication time is often absent, and the video id has to
come from a link the person copied. YouTube is read from an API that
answers with the id, an exact `publishedAt`, the channel, and integer
counts. Nothing is inferred and nothing is lossy.

Two consequences. Collection needs no scrolling at all -- a keyword and
a time window are the whole instruction. And re-checking is an id
lookup rather than a page to interpret: ask for fifty ids, and the ones
missing from the answer are the ones that no longer exist. There is no
marker list to keep up to date and no "removed video answering 200".

The quota is the real constraint. A `search.list` costs 100 units of a
10,000-unit daily default and `videos.list` costs 1, so the searches
are what to count: roughly ninety searches a day, or three hundred
re-checks of fifty ids each. Both commands report what they spent.

    python -m app.youtube collect --keyword 拉拉 --hours 24
    python -m app.youtube collect --keywords keywords.txt --hours 24
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

API_ROOT = "https://www.googleapis.com/youtube/v3"

#: Unit cost per endpoint, for reporting what a run spent.
COST = {"search": 100, "videos": 1}

#: The API caps both at 50 per call.
PAGE_SIZE = 50


class YouTubeError(RuntimeError):
    """The API refused a request, with its own explanation."""


@dataclass
class Spend:
    """What a run cost, so the daily quota is never a surprise."""

    calls: dict[str, int] = field(default_factory=dict)

    def charge(self, endpoint: str) -> None:
        self.calls[endpoint] = self.calls.get(endpoint, 0) + 1

    @property
    def units(self) -> int:
        return sum(COST.get(name, 1) * count for name, count in self.calls.items())

    def __str__(self) -> str:
        detail = ", ".join(f"{name} x{count}" for name, count in sorted(self.calls.items()))
        return f"{self.units} quota units ({detail})" if detail else "0 quota units"


#: Injected so every test runs without a key or the network.
Caller = Callable[[str, dict[str, str]], dict]


def api_key() -> str:
    """The key, from .env or the environment.

    Both, because .env is read by pydantic-settings into `settings` and
    never into os.environ -- so reading only the environment would
    ignore the file the key is supposed to live in.
    """
    from .config import settings

    key = (settings.youtube_api_key or os.environ.get("YOUTUBE_API_KEY", "")).strip()
    if not key:
        raise YouTubeError(
            "no API key. Add this line to backend/.env:\n"
            "    YOUTUBE_API_KEY=your-key-here\n"
            "Create one at console.cloud.google.com: new project, enable "
            "'YouTube Data API v3', then Credentials -> Create credentials "
            "-> API key."
        )
    return key


def call(endpoint: str, params: dict[str, str], timeout: float = 30.0) -> dict:
    """One API request. Raises YouTubeError with the API's own message."""
    query = urllib.parse.urlencode({**params, "key": api_key()})
    request = urllib.request.Request(f"{API_ROOT}/{endpoint}?{query}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(body)["error"]["message"]
        except Exception:
            message = body[:200]
        # Worth naming: this one stops collection for the day and is
        # not a bug to debug.
        if error.code == 403 and "quota" in message.lower():
            raise YouTubeError(f"daily quota exhausted: {message}") from error
        raise YouTubeError(f"HTTP {error.code}: {message}") from error
    except (urllib.error.URLError, OSError) as error:
        raise YouTubeError(f"could not reach the API: {error}") from error


# --------------------------------------------------------------------
# Searching
# --------------------------------------------------------------------


def search_ids(
    keyword: str,
    published_after: datetime,
    caller: Caller = call,
    spend: Spend | None = None,
    max_results: int = 200,
    region_code: str | None = None,
    relevance_language: str | None = None,
) -> list[str]:
    """Video ids for one keyword, newest first, since `published_after`.

    `order=date` is deliberate: the study samples what was posted in a
    window, so relevance ranking would quietly bias which of those
    videos got in.
    """
    found: list[str] = []
    page_token = ""
    while len(found) < max_results:
        params = {
            "part": "id",
            "q": keyword,
            "type": "video",
            "order": "date",
            "maxResults": str(min(PAGE_SIZE, max_results - len(found))),
            "publishedAfter": _rfc3339(published_after),
        }
        if region_code:
            params["regionCode"] = region_code
        if relevance_language:
            params["relevanceLanguage"] = relevance_language
        if page_token:
            params["pageToken"] = page_token

        payload = caller("search", params)
        if spend:
            spend.charge("search")
        for item in payload.get("items", []):
            video_id = (item.get("id") or {}).get("videoId")
            if video_id:
                found.append(video_id)

        page_token = payload.get("nextPageToken") or ""
        if not page_token:
            break
    return found


def details(
    video_ids: list[str], caller: Caller = call, spend: Spend | None = None
) -> dict[str, dict]:
    """Full records for up to any number of ids, fifty per request."""
    out: dict[str, dict] = {}
    for batch in _chunked(video_ids, PAGE_SIZE):
        payload = caller(
            "videos",
            {"part": "snippet,statistics,status", "id": ",".join(batch), "maxResults": str(PAGE_SIZE)},
        )
        if spend:
            spend.charge("videos")
        for item in payload.get("items", []):
            out[item["id"]] = item
    return out


def to_payload(item: dict) -> dict:
    """One API record, flattened onto the shape the parsers expect."""
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    return {
        "video_id": item.get("id"),
        "channel_id": snippet.get("channelId"),
        "channel_title": snippet.get("channelTitle"),
        "caption": snippet.get("title"),
        "description": (snippet.get("description") or "")[:2000] or None,
        "published_at": snippet.get("publishedAt"),
        "view_count": stats.get("viewCount"),
        "like_count": stats.get("likeCount"),
        "comment_count": stats.get("commentCount"),
        # Recorded so a later disappearance can be compared against how
        # the video was configured when it was found.
        "privacy_status": (item.get("status") or {}).get("privacyStatus"),
    }


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# --------------------------------------------------------------------
# Re-checking
# --------------------------------------------------------------------


def existing_ids(
    video_ids: list[str], caller: Caller = call, spend: Spend | None = None
) -> tuple[set[str], dict[str, str]]:
    """Which ids still exist, and each survivor's privacy status.

    An id absent from the answer no longer resolves: deleted, made
    private, or taken down. Which of those is not in the response --
    the same limit the other platforms have -- but unlike an HTML page
    there is nothing to misread, and a network failure raises instead
    of looking like a removal.
    """
    found = details(video_ids, caller=caller, spend=spend)
    statuses = {
        video_id: (item.get("status") or {}).get("privacyStatus") or "unknown"
        for video_id, item in found.items()
    }
    return set(found), statuses


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _rfc3339(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _chunked(items: list[str], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def window_start(hours: float, now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc).replace(tzinfo=None)) - timedelta(hours=hours)


# --------------------------------------------------------------------
# Storing a collection run
# --------------------------------------------------------------------


@dataclass
class CollectReport:
    keywords: int = 0
    found: int = 0
    stored: int = 0
    duplicates: int = 0
    spend: Spend = field(default_factory=Spend)

    def __str__(self) -> str:
        return (
            f"{self.keywords} keyword(s), {self.found} video(s) found, "
            f"{self.stored} stored, {self.duplicates} already had, {self.spend}"
        )


def collect(
    session,
    keywords: list[str],
    hours: float = 24.0,
    caller: Caller = call,
    now: datetime | None = None,
    participant_id: str = "API",
    max_per_keyword: int = 200,
    region_code: str | None = None,
    relevance_language: str | None = None,
) -> CollectReport:
    """Search each keyword, store every video found in the window.

    Stored through the same two layers as a phone capture -- the
    verbatim API record in `capture_events`, the typed row in
    `youtube_posts` -- so the dashboards, the CSV export and the
    re-checker need to know nothing about where a platform came from.
    The unique constraint on (participant, fingerprint, date) does the
    de-duplication, which matters because keyword searches overlap.
    """
    import json as _json

    from sqlalchemy.exc import IntegrityError

    from .config import settings
    from .models import CaptureEvent
    from .parsers import PLATFORM_TABLES

    # Configured defaults, overridable per call. None means "use the
    # configured value"; an empty string means "explicitly none".
    if relevance_language is None:
        relevance_language = settings.youtube_relevance_language
    if region_code is None:
        region_code = settings.youtube_region_code

    model, structure = PLATFORM_TABLES["youtube"]
    moment = now or datetime.now(timezone.utc).replace(tzinfo=None)
    since = window_start(hours, moment)

    report = CollectReport(keywords=len(keywords))
    # Every keyword that surfaced a video, in the order searched. A
    # video found by two keywords is one observation, but recording
    # only the first would make a per-keyword count depend on the order
    # of the keyword list -- and these lists overlap heavily by design
    # ("女同" against "女同性恋").
    seen: dict[str, list[str]] = {}
    for keyword in keywords:
        for video_id in search_ids(
            keyword,
            since,
            caller=caller,
            spend=report.spend,
            max_results=max_per_keyword,
            region_code=region_code,
            relevance_language=relevance_language,
        ):
            matched = seen.setdefault(video_id, [])
            if keyword not in matched:
                matched.append(keyword)

    report.found = len(seen)
    records = details(list(seen), caller=caller, spend=report.spend)

    for video_id, item in records.items():
        payload = to_payload(item)
        payload["feed"] = "search:" + ",".join(seen[video_id])
        # The parameters that produced this row travel with it. Change
        # them halfway through a study and the rows before and after
        # are not the same sample; without this, nothing in the data
        # would say which is which.
        payload["relevance_language"] = relevance_language or None
        payload["region_code"] = region_code or None

        event = CaptureEvent(
            participant_id=participant_id,
            device_id="youtube-api",
            platform="youtube",
            # The id is the fingerprint: unlike a screen capture there
            # is nothing approximate to key on.
            fingerprint=video_id,
            capture_date=moment.date().isoformat(),
            captured_at=moment,
            payload=_json.dumps(payload, ensure_ascii=False),
        )
        session.add(event)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            report.duplicates += 1
            continue

        row = structure(payload)
        row["video_url"] = watch_url(video_id)
        session.add(
            model(
                capture_event_id=event.id,
                participant_id=participant_id,
                captured_at=moment,
                **row,
            )
        )
        session.commit()
        report.stored += 1

    return report


def read_keywords(argument: str | None, path: str | None) -> list[str]:
    """Keywords from the command line, or one per line from a file."""
    if path:
        with open(path, encoding="utf-8") as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.startswith("#")
            ]
    return [part.strip() for part in (argument or "").split(",") if part.strip()]


def main() -> None:  # pragma: no cover - thin CLI wrapper
    import argparse

    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description="Collect YouTube via its Data API.")
    parser.add_argument("command", choices=["collect"], help="what to do")
    parser.add_argument("--keyword", help="one keyword, or several comma-separated")
    parser.add_argument("--keywords", help="path to a file with one keyword per line")
    parser.add_argument("--hours", type=float, default=24.0, help="how far back to look")
    parser.add_argument(
        "--max", type=int, default=200, dest="max_per_keyword",
        help="cap on videos per keyword (50 per search call)",
    )
    parser.add_argument(
        "--region", help="regionCode, e.g. TW or HK; overrides .env"
    )
    parser.add_argument(
        "--language",
        help="relevanceLanguage, e.g. zh-Hans; overrides .env. Pass an "
        "empty string to search without one.",
    )
    args = parser.parse_args()

    keywords = read_keywords(args.keyword, args.keywords)
    if not keywords:
        parser.error("give --keyword or --keywords")

    init_db()
    with SessionLocal() as session:
        print(
            collect(
                session,
                keywords,
                hours=args.hours,
                max_per_keyword=args.max_per_keyword,
                region_code=args.region,
                relevance_language=args.language,
            )
        )


if __name__ == "__main__":  # pragma: no cover
    main()
