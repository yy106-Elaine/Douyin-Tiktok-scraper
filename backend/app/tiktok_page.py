"""Read a TikTok video page that was fetched from a computer.

The same argument as `app/douyin_page.py`, for the same reason. The
phone reads a feed and its readings have to be stitched to a copied
link afterwards; a page fetched from the video's own URL needs no
stitch, because the id is in the address.

On TikTok the stitch failed worse than on Douyin. One evening's
collection produced 25 links and 60 screen readings of the same
videos, and the only thing that had ever joined them was proximity in
time -- which put one video's handle beside another's caption. Undone,
the table is honest and empty: 25 rows with an id and nothing else.
This is what fills them, without a guess.

**Same company, different wording.** TikTok and Douyin hand over the
same kind of record, so everything about *finding* it lives in
`app/pagedata.py`. What differs is the spelling, and only that is
here:

    aweme_id      id
    statistics    stats / statsV2
    create_time   createTime
    digg_count    diggCount
    unique_id     uniqueId
    sec_uid       secUid

One difference matters beyond spelling: TikTok's record carries the
author's `uniqueId`, which *is* the @handle. On Douyin the 抖音号 is
not in the video record at all and needs a second visit to the
profile -- so there is no TikTok equivalent of `app/fetch_authors.py`
to run, and there does not need to be.

**Unverified.** The shapes below come from the published behaviour of
these pages, not from a response read here. `--dump` writes the HTML
of any page this fails on, which is what turns a guess into a
selector.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from html import unescape

from .pagedata import (
    Fetched,
    VideoFacts,
    addresses,
    dicts_with,
    embedded,
    first_present as _first,
    seconds_to_utc as _seconds_to_utc,
    text_of as _text,
    whole_number as _int,
)
from .pagedata import fetch as _fetch

#: A desktop browser. Unlike Douyin's share host, tiktok.com serves
#: the rendered page to a desktop agent and treats an unfamiliar one
#: as a bot.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

#: The handle is part of the address. `@i` works when it is unknown --
#: TikTok resolves the video by id and redirects -- which is the same
#: placeholder `app/links.py` uses when building a canonical URL.
VIDEO_URL = "https://www.tiktok.com/@{handle}/video/{video_id}"


def video_url(video_id: str, handle: str | None = None) -> str:
    return VIDEO_URL.format(
        handle=(handle or "i").lstrip("@") or "i", video_id=video_id
    )


def fetch(url: str, timeout: float = 20.0) -> Fetched:
    """One anonymous request. Usually a wall; see `app/browser.py`."""
    return _fetch(url, timeout=timeout, user_agent=USER_AGENT)


_META = re.compile(
    r'<meta[^>]+(?:property|name)="(?P<key>[^"]+)"[^>]+content="(?P<value>[^"]*)"',
    re.IGNORECASE,
)


def _meta_tags(html: str) -> dict[str, str]:
    return {m.group("key").lower(): unescape(m.group("value")) for m in _META.finditer(html)}


def video_facts(html: str, payloads: Sequence[dict] = ()) -> VideoFacts:
    """What the page says about the video, best source first.

    A record captured from the page's own API beats one embedded in
    the HTML, and both beat the meta tags, which carry a caption and
    nothing countable. `parsed_by` records which it was, because a row
    read off the surface is worth less than one read out of the data
    and the difference should be visible without re-fetching.
    """
    for source, blobs in (("api", list(payloads)), ("embedded", list(embedded(html or "")))):
        for blob in blobs:
            for record in dicts_with(blob, ("desc", "author")):
                author = record.get("author")
                if not isinstance(author, dict):
                    continue
                stats = record.get("stats")
                if not isinstance(stats, dict):
                    stats = record.get("statsV2")
                if not isinstance(stats, dict):
                    stats = {}
                return VideoFacts(
                    video_id=_text(_first(record, "id", "awemeId", "aweme_id")),
                    sec_uid=_text(_first(author, "secUid", "sec_uid")),
                    author_name=_text(_first(author, "nickname", "uniqueId")),
                    # `uniqueId` is the @handle itself -- no second
                    # visit needed, unlike Douyin's 抖音号.
                    author_handle=_text(_first(author, "uniqueId", "unique_id")),
                    caption=_text(record.get("desc")),
                    posted_on=_seconds_to_utc(
                        _first(record, "createTime", "create_time")
                    ),
                    like_count=_int(_first(stats, "diggCount", "digg_count")),
                    comment_count=_int(
                        _first(stats, "commentCount", "comment_count")
                    ),
                    share_count=_int(_first(stats, "shareCount", "share_count")),
                    collect_count=_int(
                        _first(stats, "collectCount", "collect_count")
                    ),
                    parsed_by=source,
                )

    tags = _meta_tags(html or "")
    caption = _text(tags.get("og:description") or tags.get("description"))
    if not caption:
        return VideoFacts()
    return VideoFacts(caption=caption, parsed_by="surface")


def file_urls(
    html: str = "", payloads: Sequence[dict] = (), video_id: str | None = None
) -> list[str]:
    """Every address the record offers for the video file itself.

    Filtered to the video asked for when `video_id` is given, and the
    filter demands a matching id rather than the absence of a
    conflicting one -- the same guard as on Douyin, for the same
    reason: a page carries its neighbours' records too, and some of
    them name no id at their own level.
    """
    # Both sources, because the record does not always arrive the
    # same way: Douyin's comes back as a captured API response, and
    # TikTok writes it into the page. Reading only the responses left
    # every TikTok video reporting "no file address for this id".
    urls: list[str] = []
    for blob in list(payloads) + list(embedded(html or "")):
        for record in dicts_with(blob, ("video",)):
            if video_id is not None:
                if _text(_first(record, "id", "awemeId", "aweme_id")) != video_id:
                    continue
            video = record.get("video")
            if not isinstance(video, dict):
                continue
            # TikTok writes these as bare strings, and the ladder of
            # encodings under a capitalised key.
            urls += addresses(video, "playAddr", "play_addr", "downloadAddr",
                              "download_addr")
            for rung in _first(video, "bitrateInfo", "bit_rate") or ():
                if isinstance(rung, dict):
                    urls += addresses(rung, "PlayAddr", "playAddr", "play_addr")

    seen: set[str] = set()
    ordered = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered
