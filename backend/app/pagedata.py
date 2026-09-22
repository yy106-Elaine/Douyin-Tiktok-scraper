"""Finding the record a page carries, whichever site rendered it.

Douyin and TikTok are built by the same company and hand their data
over the same way: a JSON blob in the HTML, or an XHR the page makes
while rendering. What differs is the wording -- `aweme_id` against
`id`, `statistics` against `stats`, `create_time` against
`createTime` -- and the addresses. That belongs in a per-site module;
this one holds what is genuinely common, so a fix to the awkward part
of it happens once.

The awkward part is finding the blob at all. It is assigned to a
window property on some builds and written into a `<script>` tag on
others; the JSON may be plain, HTML-escaped, percent-encoded, or
both; and a regex cannot find the end of a nested object, so the
closing brace has to be counted with quotes and escapes tracked. All
of that was learned from real pages and none of it is documented, so
it is kept in one place rather than reproduced per site.

Nothing here knows a path through the data. Records are found by the
fields they hold, because these shapes change and a fixed path breaks
silently -- it returns nothing, which reads exactly like a video with
nothing in it.
"""
from __future__ import annotations

import gzip
import json
import re
import urllib.error
import urllib.request
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from urllib.parse import unquote


@dataclass
class Fetched:
    """A page, or the reason there isn't one.

    `payloads` holds JSON the page itself fetched while rendering.
    Neither site reliably puts the video in its HTML -- douyin.com's
    `RENDER_DATA` carries the page shell and not even the video's id
    -- so the record arrives in an XHR after hydration. Captured, that
    response is the same record the app reads, and no selector has to
    be guessed at.
    """

    url: str
    html: str | None = None
    http_status: int | None = None
    error: str | None = None
    payloads: list[dict] = field(default_factory=list)


def fetch(
    url: str,
    timeout: float = 20.0,
    user_agent: str = "",
    accept_language: str = "en-US,en;q=0.9",
) -> Fetched:
    """One anonymous request, with no session and no browser."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Language": accept_language,
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
    r"window\.(?:_ROUTER_DATA|_SSR_HYDRATED_DATA|__INITIAL_STATE__"
    r"|__UNIVERSAL_DATA_FOR_REHYDRATION__)\s*=\s*",
)
#: State written into a script tag rather than assigned. douyin.com
#: percent-encodes the JSON inside `RENDER_DATA`; tiktok.com writes
#: `__UNIVERSAL_DATA_FOR_REHYDRATION__` plainly. The pattern is loose
#: because the id changes and the type attribute is not always there.
_JSON_SCRIPT = re.compile(
    r"<script[^>]*\bid=\"[^\"]*(?:RENDER_DATA|__RENDER_DATA__|__NEXT_DATA__"
    r"|__UNIVERSAL_DATA_FOR_REHYDRATION__)[^\"]*\""
    r"[^>]*>(.*?)</script>",
    re.DOTALL | re.IGNORECASE,
)
_ANY_JSON_SCRIPT = re.compile(
    r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', re.DOTALL
)


def balanced(text: str, start: int) -> str | None:
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
        blob = balanced(html, match.end())
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
            # Four spellings, because these sites have used more than
            # one: plain JSON, HTML-escaped, percent-encoded, and both.
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


def whole_number(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def first_present(mapping: dict, *keys: str) -> object:
    """The first key present, not the first that is truthy.

    A video with zero likes is a reading, and `a or b` turns it into
    a missing value. These pages carry plenty of zeroes -- a post with
    no comments yet renders 抢首评 -- so this distinction is the
    difference between "none" and "we did not look".
    """
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def text_of(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def seconds_to_utc(value: object) -> datetime | None:
    """A Unix timestamp as the naive UTC instant the columns hold."""
    seconds = whole_number(value)
    if not seconds or not (1_400_000_000 < seconds < 4_000_000_000):
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)


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


def addresses(record: dict, *keys: str) -> list[str]:
    """Playable URLs out of one record's address fields.

    Both sites hold them as `{"url_list": [...]}` (or `urlList`), and
    several of them: one URL expires, is region-restricted or answers
    403, and the next is usually the same footage from another host.
    TikTok also writes a bare string in some fields, which is why a
    string is accepted as well as a list.
    """
    found: list[str] = []
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.startswith("http"):
            found.append(value)
            continue
        if not isinstance(value, dict):
            continue
        urls = first_present(value, "url_list", "urlList", "UrlList")
        if isinstance(urls, str):
            urls = [urls]
        for url in urls or ():
            if isinstance(url, str) and url.startswith("http"):
                found.append(url)
    return found
