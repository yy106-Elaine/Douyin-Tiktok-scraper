"""Read a Douyin page that was fetched from a computer.

Why a computer at all, when the phone is already there: the phone
reads a feed. It sees a post for a second or two, at whatever moment
the loop happened to look, and what it read has to be stitched to a
copied link afterwards. Every wrong row in this study so far came out
of that stitch -- one video's counts beside another's caption, a
neighbouring author's 抖音号, a caption that had not drawn yet.

A page fetched from the video's own URL needs no stitch: the id is in
the address, so everything parsed out of the response belongs to it by
construction. The phone keeps the job only it can do -- reaching posts
that the web search will not return -- and hands over a link.

**Parsing strategy.** Douyin's share host renders server-side and
embeds the whole record as JSON in a `<script>`; that is the good
path and it is tried first. The shapes of those blobs change, so
nothing here depends on a fixed path through them: it walks every
embedded object and takes the first that looks like a video (or an
author), by the fields present rather than by where they sit. When
that finds nothing there is a second pass over `og:` meta tags and
the visible text, which gets the caption and the date but not the
counts.

Whatever matched is recorded in `parsed_by`, because a row read out
of the page's own data is worth more than one scraped off its
surface, and the difference should be visible without re-fetching.

**Unverified.** This was written without being able to reach Douyin:
the shapes below come from the share host's published behaviour, not
from a response anyone here has seen. `--dump` writes the HTML of any
page it fails on, which is what turns a guess into a selector.
"""
from __future__ import annotations

import gzip
import json
import re
import urllib.error
import urllib.request
import zlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import unquote

#: Douyin prints times in Beijing time; the columns hold UTC.
_BEIJING_OFFSET = timedelta(hours=8)

#: A phone browser. The share host serves the rendered page to one;
#: a desktop agent is more often answered with an app-download wall.
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 "
    "Safari/604.1"
)

VIDEO_URL = "https://www.iesdouyin.com/share/video/{video_id}/"
AUTHOR_URL = "https://www.iesdouyin.com/share/user/{sec_uid}"


@dataclass
class Fetched:
    """A page, or the reason there isn't one.

    `payloads` holds JSON the page itself fetched while rendering.
    douyin.com does not put the video in its HTML -- `RENDER_DATA`
    carries the page shell and not even the video's id -- so the
    record arrives in an XHR after hydration. Captured, that response
    is the same aweme record the app reads, and no selector has to be
    guessed at.
    """

    url: str
    html: str | None = None
    http_status: int | None = None
    error: str | None = None
    payloads: list[dict] = field(default_factory=list)


def fetch(url: str, timeout: float = 20.0) -> Fetched:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            encoding = (response.headers.get("Content-Encoding") or "").lower()
            if encoding == "gzip":
                raw = gzip.decompress(raw)
            elif encoding == "deflate":
                raw = zlib.decompress(raw)
            charset = response.headers.get_content_charset() or "utf-8"
            return Fetched(
                url=url,
                html=raw.decode(charset, errors="replace"),
                http_status=response.status,
            )
    except urllib.error.HTTPError as problem:
        return Fetched(url=url, http_status=problem.code, error="HTTPError")
    except (urllib.error.URLError, OSError, ValueError) as problem:
        return Fetched(url=url, error=type(problem).__name__)


# --------------------------------------------------------------------
# Finding the data the page carries
# --------------------------------------------------------------------

#: Assignments whose right-hand side is the page's own state.
_ASSIGNED = re.compile(
    r"window\.(?:_ROUTER_DATA|_SSR_HYDRATED_DATA|__INITIAL_STATE__)\s*=\s*",
)
#: douyin.com renders its state into a script tag rather than
#: assigning it, and percent-encodes the JSON inside. `RENDER_DATA` is
#: the one it has used; the pattern is loose because the id changes
#: and the type attribute is not always there.
_JSON_SCRIPT = re.compile(
    r"<script[^>]*\bid=\"[^\"]*(?:RENDER_DATA|__RENDER_DATA__|__NEXT_DATA__)[^\"]*\""
    r"[^>]*>(.*?)</script>",
    re.DOTALL | re.IGNORECASE,
)
_ANY_JSON_SCRIPT = re.compile(
    r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', re.DOTALL
)


def _balanced(text: str, start: int) -> str | None:
    """The JSON object beginning at `start`, by brace counting.

    A regex cannot find the end of a nested object, and the blob is
    followed by more script, so the end has to be counted. Quotes and
    escapes are tracked so a brace inside a caption does not close it.
    """
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def embedded(html: str) -> Iterator[dict]:
    """Every JSON object the page embeds, parsed."""
    for match in _ASSIGNED.finditer(html):
        blob = _balanced(html, match.end())
        if not blob:
            continue
        try:
            yield json.loads(blob)
        except ValueError:
            # Some builds percent-encode the blob before assigning it.
            try:
                yield json.loads(unquote(blob))
            except ValueError:
                continue
    for pattern in (_JSON_SCRIPT, _ANY_JSON_SCRIPT):
        for match in pattern.finditer(html):
            body = match.group(1).strip()
            # Four spellings, because the site has used more than one:
            # plain JSON, HTML-escaped, percent-encoded, and both.
            for decode in (
                lambda text: text,
                unescape,
                unquote,
                lambda text: unquote(unescape(text)),
            ):
                try:
                    yield json.loads(decode(body))
                    break
                except ValueError:
                    continue


def dicts_with(obj: object, required: tuple[str, ...]) -> Iterator[dict]:
    """Walk anything and yield the dicts holding all of `required`.

    Keyed on what a record contains rather than where it sits, so a
    rearranged page still parses. The shapes of these blobs are not
    documented and do change.
    """
    if isinstance(obj, dict):
        if all(key in obj for key in required):
            yield obj
        for value in obj.values():
            yield from dicts_with(value, required)
    elif isinstance(obj, list):
        for value in obj:
            yield from dicts_with(value, required)


def _int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _first(mapping: dict, *keys: str) -> object:
    """The first key present, not the first that is truthy.

    A video with zero likes is a reading, and `a or b` turns it into
    a missing value. Douyin's share pages carry plenty of zeroes --
    a post with no comments yet renders 抢首评 -- so this distinction
    is the difference between "none" and "we did not look".
    """
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _seconds_to_utc(value: object) -> datetime | None:
    """A Unix timestamp as the naive UTC instant the columns hold."""
    seconds = _int(value)
    if not seconds or not (1_400_000_000 < seconds < 4_000_000_000):
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------
# What the pages say
# --------------------------------------------------------------------


@dataclass
class VideoFacts:
    video_id: str | None = None
    sec_uid: str | None = None
    author_name: str | None = None
    author_handle: str | None = None
    caption: str | None = None
    posted_on: datetime | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    collect_count: int | None = None
    parsed_by: str | None = None

    def is_empty(self) -> bool:
        """Nothing was read. Zero likes is something read."""
        return not any(
            (
                self.caption,
                self.author_name,
                self.posted_on,
                self.like_count is not None,
            )
        )


_POSTED = re.compile(r"发布[时時]间[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2}[^<\n]*)")
_HANDLE = re.compile(r"抖音号[：:]\s*([A-Za-z0-9._\-]+)")
#: The account id, as it appears in every link to a profile. Worth
#: reading even when nothing else could be: it is what the profile
#: pass is keyed on, so one of these turns an unreadable video page
#: into a readable author.
_SEC_UID_HREF = re.compile(r"/user/(MS4w[A-Za-z0-9_\-]{10,})")

_META = re.compile(
    r'<meta[^>]+(?:property|name)="(?P<key>[^"]+)"[^>]+content="(?P<value>[^"]*)"',
    re.IGNORECASE,
)


def _meta_tags(html: str) -> dict[str, str]:
    return {m.group("key").lower(): unescape(m.group("value")) for m in _META.finditer(html)}


def video_facts(html: str, payloads: Sequence[dict] = ()) -> VideoFacts:
    """Read a video page.

    In order of how attached the answer is to the video: what the
    page's own API returned, then anything embedded in the HTML, then
    the surface.
    """
    for blob in list(payloads) + list(embedded(html)):
        for record in dicts_with(blob, ("desc", "author")):
            author = record.get("author") or {}
            if not isinstance(author, dict):
                continue
            statistics = record.get("statistics") or {}
            if not isinstance(statistics, dict):
                statistics = {}
            facts = VideoFacts(
                video_id=_text(_first(record, "aweme_id", "awemeId")),
                sec_uid=_text(_first(author, "sec_uid", "secUid")),
                author_name=_text(author.get("nickname")),
                author_handle=_text(
                    _first(author, "unique_id", "uniqueId", "short_id")
                ),
                caption=_text(record.get("desc")),
                posted_on=_seconds_to_utc(_first(record, "create_time", "createTime")),
                like_count=_int(_first(statistics, "digg_count", "diggCount")),
                comment_count=_int(
                    _first(statistics, "comment_count", "commentCount")
                ),
                share_count=_int(_first(statistics, "share_count", "shareCount")),
                collect_count=_int(
                    _first(statistics, "collect_count", "collectCount")
                ),
                parsed_by="api" if blob in list(payloads) else "embedded",
            )
            if not facts.is_empty():
                return facts

    # Nothing embedded we could read. The surface still carries the
    # caption and the date, and says so in the open.
    meta = _meta_tags(html)
    posted = _POSTED.search(html)
    facts = VideoFacts(
        author_name=_text(meta.get("og:title")),
        caption=_text(meta.get("og:description")) or _text(meta.get("description")),
        parsed_by="surface",
    )
    if posted:
        facts.posted_on = _parse_shown_time(posted.group(1))
    handle = _HANDLE.search(html)
    if handle:
        facts.author_handle = handle.group(1)
    account = _SEC_UID_HREF.search(html)
    if account:
        facts.sec_uid = account.group(1)
    return facts


#: Where a video record keeps its playable addresses. Several, in
#: preference order: `play_addr` is what the page itself plays;
#: `download_addr` is the same video as the app's own save button
#: produces; `bit_rate` holds the ladder of encodings, used only when
#: the first two are missing.
def file_urls(payloads: Sequence[dict] = (), video_id: str | None = None) -> list[str]:
    """Every address the record offers for the video file itself.

    Returned in the order to try them, duplicates removed. The list
    is long on purpose: a single URL expires, is region-restricted or
    answers 403, and the next one down is usually the same footage
    from another host.

    Filtered to the video asked for when `video_id` is given, for the
    same reason `app.fetch_videos` verifies the id: a page asked for
    a removed video answers with a different video's record, and
    downloading that would file someone else's footage under this id.
    """
    urls: list[str] = []

    def take(addr: object) -> None:
        if not isinstance(addr, dict):
            return
        for url in addr.get("url_list") or ():
            if isinstance(url, str) and url.startswith("http"):
                urls.append(url)

    for blob in payloads:
        for record in dicts_with(blob, ("video",)):
            if video_id is not None:
                found = _text(_first(record, "aweme_id", "awemeId"))
                if found and found != video_id:
                    continue
            video = record.get("video")
            if not isinstance(video, dict):
                continue
            take(_first(video, "play_addr", "playAddr"))
            take(_first(video, "download_addr", "downloadAddr"))
            for rung in video.get("bit_rate") or ():
                if isinstance(rung, dict):
                    take(_first(rung, "play_addr", "playAddr"))

    seen: set[str] = set()
    ordered = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _parse_shown_time(shown: str) -> datetime | None:
    """`2026-09-20 23:10` as the page prints it.

    Douyin renders this in Beijing time (UTC+8) and the columns hold
    UTC, so it is converted. A date with no clock is left alone --
    midnight would be a fact nobody observed.
    """
    text = shown.strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            naive = datetime.strptime(text[: len(pattern) + 4], pattern)
        except ValueError:
            continue
        return naive - _BEIJING_OFFSET
    return None



@dataclass
class AuthorFacts:
    sec_uid: str | None = None
    author_handle: str | None = None
    author_name: str | None = None
    signature: str | None = None
    ip_location: str | None = None
    follower_count: int | None = None
    following_count: int | None = None
    total_favorited: int | None = None
    video_count: int | None = None
    parsed_by: str | None = None
    #: Ids of the videos the profile lists, so a profile visit can
    #: also tell us what else the account has posted.
    video_ids: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any((self.author_handle, self.author_name, self.follower_count))


def author_facts(html: str, payloads: Sequence[dict] = ()) -> AuthorFacts:
    """Read a profile page. The 抖音号 is the point of the visit."""
    for blob in list(payloads) + list(embedded(html)):
        for record in dicts_with(blob, ("nickname", "sec_uid")):
            facts = AuthorFacts(
                sec_uid=_text(record.get("sec_uid")),
                author_handle=_text(record.get("unique_id"))
                or _text(record.get("short_id")),
                author_name=_text(record.get("nickname")),
                signature=_text(record.get("signature")),
                ip_location=_text(record.get("ip_location"))
                or _text(record.get("ipLocation")),
                follower_count=_int(record.get("follower_count")),
                following_count=_int(record.get("following_count")),
                total_favorited=_int(record.get("total_favorited")),
                video_count=_int(record.get("aweme_count")),
                parsed_by="api" if blob in list(payloads) else "embedded",
            )
            if not facts.is_empty():
                facts.video_ids = _video_ids(blob)
                return facts

    meta = _meta_tags(html)
    facts = AuthorFacts(author_name=_text(meta.get("og:title")), parsed_by="surface")
    handle = _HANDLE.search(html)
    if handle:
        facts.author_handle = handle.group(1)
    location = re.search(r"IP[属屬]地[：:]\s*([^\s<]{1,16})", html)
    if location:
        facts.ip_location = location.group(1)
    return facts


def _video_ids(blob: object) -> list[str]:
    seen: list[str] = []
    for record in dicts_with(blob, ("aweme_id",)):
        value = _text(record.get("aweme_id"))
        if value and value.isdigit() and value not in seen:
            seen.append(value)
    return seen
