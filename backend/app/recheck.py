"""Revisit collected links and record whether each video is still there.

This is the takedown instrument. It visits a video's public page, keeps
what the server returned, and classifies afterwards -- see
`app/models.py::LinkCheck` for why the verdict is not stored.

Three things make a naive check wrong, and each one is handled here
rather than left to the reader:

**A removed video does not answer 404.** Both platforms commonly serve
HTTP 200 with a page that says the video is unavailable. "Did the
request succeed" therefore reports every video as alive. The decision
is made on the page's own wording, and the status code is only one
input among several.

**A failed request is not a takedown.** A timeout, a DNS failure, a
rate-limit page or a bot challenge all mean "no information", and each
one is recorded as such. Counting them as removals would manufacture
exactly the finding the study is looking for.

**One vantage point cannot see a regional block.** A video restricted
in one country and visible in another is indistinguishable, from here,
from a video that is fine. That is a limitation of the design, not
something the code can resolve; `docs/METHODOLOGY.md` says so and the
dashboard repeats it.

Runs on demand -- `python -m app.recheck` -- because a check that runs
unattended against someone else's servers is a different kind of thing
from one a researcher performs.
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .links import canonical_url_for
from .models import LinkCheck, SharedLink
from .parsers import PLATFORM_TABLES

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

#: How much of the response to keep. Enough to re-read the wording a
#: later marker list cares about; not the whole page.
EXCERPT_LIMIT = 1_200

# --------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------

ALIVE = "alive"
#: The page says the video is not there. Which party removed it is a
#: separate question this cannot answer on its own.
GONE = "gone"
#: The account is unreachable, so every one of its videos is too.
AUTHOR_GONE = "author gone"
#: Reachable but withheld: private account, or a sign-in wall.
WITHHELD = "withheld"
#: The request never completed. No information about the video.
UNREACHABLE = "unreachable"
#: The platform answered, but with a challenge or something unrecognised.
#: Loud on purpose: it means the marker list needs a look, and these
#: rows must stay out of any takedown rate.
UNKNOWN = "unknown"

#: Verdicts that carry no information about the video's existence and
#: must be excluded from a rate rather than counted either way.
NO_INFORMATION = frozenset({UNREACHABLE, UNKNOWN})

# --------------------------------------------------------------------
# Marker phrases
# --------------------------------------------------------------------
#
# These decide the classification, and they are the part most likely to
# be wrong: they come from the platforms' published wording, not from a
# removed video observed here. Two safeguards. A page matching nothing
# is UNKNOWN, never "alive" -- so a stale list shows up as a growing
# unknown count instead of a quietly wrong survival curve. And the
# response excerpt is stored, so a corrected list can be applied to
# checks already recorded.
#
# Verify against one genuinely removed video before trusting a rate.

_MARKERS: tuple[tuple[str, str, str], ...] = (
    # (name, verdict, pattern)
    ("tiktok_unavailable", GONE, r"video (?:is )?currently unavailable"),
    ("tiktok_removed", GONE, r"this video (?:has been|was) removed"),
    ("tiktok_violating", GONE, r"violat(?:ing|ion of) our community guidelines"),
    ("tiktok_no_account", AUTHOR_GONE, r"couldn'?t find this account"),
    ("tiktok_account_banned", AUTHOR_GONE, r"account (?:was |has been )?banned"),
    ("tiktok_private", WITHHELD, r"this account is private"),
    ("tiktok_login", WITHHELD, r"log in to (?:continue|tiktok)"),
    ("tiktok_captcha", UNKNOWN, r"verify to continue|captcha|unusual traffic"),
    ("douyin_deleted", GONE, r"该作品已(?:被)?删除|内容不存在|作品不存在"),
    ("douyin_gone", GONE, r"视频不见了|已下架|无法查看"),
    ("douyin_account_gone", AUTHOR_GONE, r"该账号已注销|账号不存在|用户不存在"),
    ("douyin_private", WITHHELD, r"私密账号|仅自己可见|需要关注"),
    ("douyin_captcha", UNKNOWN, r"验证|滑块|访问频繁"),
)

_COMPILED = tuple(
    (name, verdict, re.compile(pattern, re.IGNORECASE)) for name, verdict, pattern in _MARKERS
)

#: Order of precedence when several markers match. A challenge means we
#: learned nothing and outranks everything; an absent account explains
#: an absent video, so it outranks the video's own wording.
_PRECEDENCE = (UNKNOWN, AUTHOR_GONE, GONE, WITHHELD)

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<(?:script|style)[^>]*>.*?</(?:script|style)>", re.IGNORECASE | re.DOTALL)
_ANY_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


# --------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------


@dataclass
class FetchResult:
    """What one visit returned, before any interpretation."""

    status: int | None = None
    final_url: str | None = None
    body: str = ""
    error: str | None = None


#: Injected so the classification is testable without the network, and
#: so a caller can substitute its own proxy or rate-limit policy.
Fetcher = Callable[[str], FetchResult]


def fetch(url: str, timeout: float = 20.0) -> FetchResult:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(200_000).decode("utf-8", errors="replace")
            return FetchResult(
                status=response.status, final_url=response.geturl(), body=body
            )
    except urllib.error.HTTPError as error:
        # An HTTP error status is an answer, not a failure: 404 is the
        # clearest removal signal either platform gives.
        body = ""
        try:
            body = error.read(200_000).decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            pass
        return FetchResult(status=error.code, final_url=error.url, body=body)
    except (urllib.error.URLError, OSError, ValueError) as error:
        return FetchResult(error=type(error).__name__)


# --------------------------------------------------------------------
# Reading a response
# --------------------------------------------------------------------


def page_title(body: str) -> str | None:
    match = _TITLE.search(body or "")
    if not match:
        return None
    return _SPACE.sub(" ", _ANY_TAG.sub(" ", match.group(1))).strip()[:500] or None


def excerpt(body: str) -> str:
    """Visible-ish text, bounded, for re-reading a check later."""
    without_code = _TAGS.sub(" ", body or "")
    return _SPACE.sub(" ", _ANY_TAG.sub(" ", without_code)).strip()[:EXCERPT_LIMIT]


def matched_markers(text: str) -> list[tuple[str, str]]:
    """Every marker that fires, as (name, verdict) pairs."""
    return [
        (name, verdict) for name, verdict, pattern in _COMPILED if pattern.search(text or "")
    ]


def searchable_text(check: LinkCheck) -> str:
    """Title plus excerpt -- everywhere the wording could be."""
    return f"{check.page_title or ''}\n{check.excerpt or ''}"


#: `LinkCheck.evidence` values, and what each one means. These are
#: facts about the exchange rather than wording on a page, which is
#: why they outrank the markers: a site that answers a request for a
#: removed video by serving a different one leaves no wording to find.
SERVED_ANOTHER = "served another video"
ID_CONFIRMED = "id confirmed"

_BY_EVIDENCE = {
    SERVED_ANOTHER: GONE,
    ID_CONFIRMED: ALIVE,
}


def classify(check: LinkCheck) -> str:
    """The verdict for one recorded check.

    Pure and stored nowhere, so correcting it re-reads history rather
    than requiring new collection.
    """
    if check.error:
        return UNREACHABLE

    # What the exchange established beats what the page said: the page
    # for a removed Douyin video says nothing about removal.
    if check.evidence in _BY_EVIDENCE:
        return _BY_EVIDENCE[check.evidence]

    verdicts = {verdict for _, verdict in matched_markers(searchable_text(check))}
    for candidate in _PRECEDENCE:
        if candidate in verdicts:
            return candidate

    if check.http_status == 404 or check.http_status == 410:
        return GONE
    if check.http_status in (403, 451):
        # 451 is "unavailable for legal reasons"; 403 here is more
        # often a bot wall than a removal, so neither is called GONE
        # without wording to back it.
        return WITHHELD if check.http_status == 451 else UNKNOWN
    if check.http_status == 429 or (check.http_status or 0) >= 500:
        return UNKNOWN
    if check.http_status == 200:
        # A video page that redirected to the site root or to a login
        # path is not the video.
        if check.final_url and _looks_like_a_dead_end(check.final_url):
            return WITHHELD
        return ALIVE
    return UNKNOWN


def _looks_like_a_dead_end(url: str) -> bool:
    lowered = url.lower()
    if "/login" in lowered or "/signup" in lowered:
        return True
    # Stripped back to a bare host: no path left to be a video.
    return bool(re.fullmatch(r"https?://[^/]+/?", lowered))


# --------------------------------------------------------------------
# What to check, and when
# --------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    platform: str
    video_id: str
    url: str
    author_handle: str | None
    #: Earliest moment this video is known to have existed.
    first_seen: datetime


#: Checks get sparser as a video ages, because removals cluster early
#: and every request is borrowed from someone else's servers. Each
#: entry is (age of the video, minimum gap between checks).
CADENCE: tuple[tuple[timedelta, timedelta], ...] = (
    (timedelta(hours=48), timedelta(hours=8)),
    (timedelta(days=14), timedelta(hours=20)),
    (timedelta(days=90), timedelta(days=6)),
)
#: Anything older than the last tier.
CADENCE_FLOOR = timedelta(days=27)

#: Platforms whose checks go through an API in batches, and therefore
#: cost almost nothing: YouTube answers fifty ids per request for one
#: quota unit, so a sweep of the whole corpus is two units.
#:
#: The cadence exists to keep a page-by-page fetch from hammering a
#: site. Applying it where a check is nearly free buys nothing and
#: costs the only thing this table is for: a removal is dated to the
#: gap between the check that found it alive and the one that found
#: it gone, so a wider gap is a vaguer answer. These are always due.
BATCHED = frozenset({"youtube"})


def minimum_gap(age: timedelta, platform: str | None = None) -> timedelta:
    if platform in BATCHED:
        return timedelta(0)
    for limit, gap in CADENCE:
        if age <= limit:
            return gap
    return CADENCE_FLOOR


def collected_targets(session: Session) -> list[Target]:
    """Every in-scope video with an id, from posts and from links alike.

    In scope, not merely collected. A YouTube search for 拉拉 returns
    adult nappies and a children's cartoon, and 1,072 of 1,126 rows
    were excluded by the topic filter -- yet all of them were being
    re-checked daily. That cost is the smaller half of it: a takedown
    rate computed over them is a rate for Japanese vlogs and product
    listings, not for the corpus, and it was being read as the corpus's.

    The filter is the same one the dashboard and the CSV export use,
    so a row re-marked in scope starts being tracked at the next run
    and one re-marked out of it stops -- the checks already made stay
    on file either way, and the findings are recomputed from them.

    A link that never paired to a post has no relevance to read. Those
    are kept: on Douyin and TikTok the search is the filter, and a
    copied link is a video someone chose to collect by hand.
    """
    from .views import in_scope_filter

    found: dict[str, Target] = {}

    for platform, (model, _) in PLATFORM_TABLES.items():
        for post in session.scalars(
            select(model)
            .where(model.video_id.isnot(None), in_scope_filter(model, platform))
            .order_by(model.captured_at)
        ):
            found.setdefault(
                post.video_id,
                Target(
                    platform=platform,
                    video_id=post.video_id,
                    url=post.video_url
                    or canonical_url_for(platform, post.video_id, post.author_handle),
                    author_handle=post.author_handle,
                    first_seen=post.captured_at,
                ),
            )

    # A link that never paired to a post is still a video to re-check.
    for link in session.scalars(
        select(SharedLink).where(SharedLink.video_id.isnot(None)).order_by(SharedLink.shared_at)
    ):
        found.setdefault(
            link.video_id,
            Target(
                platform=link.platform,
                video_id=link.video_id,
                url=link.canonical_url
                or canonical_url_for(link.platform, link.video_id, link.author_handle),
                author_handle=link.author_handle,
                first_seen=link.shared_at,
            ),
        )

    return sorted(found.values(), key=lambda target: target.first_seen)


def last_checked(session: Session) -> dict[str, datetime]:
    checks: dict[str, datetime] = {}
    for check in session.scalars(
        select(LinkCheck)
        .where(LinkCheck.target_kind == "video")
        .order_by(LinkCheck.checked_at)
    ):
        if check.video_id:
            checks[check.video_id] = check.checked_at
    return checks


def disappeared(session: Session) -> set[str]:
    """Videos whose check history already says they are gone.

    Computed from the stored checks, like every other finding, so a
    corrected marker list changes this too.
    """
    from .survival import findings

    return {
        finding.video_id
        for finding in findings(session)
        if finding.outcome is not None
    }


def due_targets(
    session: Session,
    now: datetime | None = None,
    targets: Iterable[Target] | None = None,
    skip_gone: bool = False,
) -> list[Target]:
    """Targets worth checking again now.

    A video already found gone is still checked, because a removal
    reversed is a finding: an appeal that succeeded, or a block that
    was temporary. It costs nearly nothing to keep looking -- on
    YouTube it is part of a batch, and on the page platforms an older
    video is due only every few weeks.

    `skip_gone` stops it anyway, for a run that has a budget to
    protect. It buys little: the videos still being watched are the
    ones a cadence actually spends requests on.
    """
    moment = now or _utcnow()
    seen = last_checked(session)
    gone = disappeared(session) if skip_gone else set()
    due = []
    for target in targets if targets is not None else collected_targets(session):
        if target.video_id in gone:
            continue
        previous = seen.get(target.video_id)
        if previous is None:
            due.append(target)
            continue
        if moment - previous >= minimum_gap(
            moment - target.first_seen, target.platform
        ):
            due.append(target)
    return due


# --------------------------------------------------------------------
# Running a round
# --------------------------------------------------------------------


@dataclass
class RecheckReport:
    checked: int = 0
    verdicts: dict[str, int] = field(default_factory=dict)

    def record(self, verdict: str) -> None:
        self.checked += 1
        self.verdicts[verdict] = self.verdicts.get(verdict, 0) + 1

    def __str__(self) -> str:
        if not self.checked:
            return "nothing due"
        counts = ", ".join(f"{name} {count}" for name, count in sorted(self.verdicts.items()))
        return f"checked {self.checked}: {counts}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _record(
    session: Session,
    target: Target,
    kind: str,
    url: str,
    result: FetchResult,
    now: datetime,
) -> LinkCheck:
    check = LinkCheck(
        platform=target.platform,
        target_kind=kind,
        video_id=target.video_id if kind == "video" else None,
        author_handle=target.author_handle,
        url=url,
        checked_at=now,
        http_status=result.status,
        final_url=result.final_url,
        page_title=page_title(result.body),
        excerpt=excerpt(result.body) or None,
        body_bytes=len(result.body) or None,
        error=result.error,
    )
    check.markers = (
        ",".join(name for name, _ in matched_markers(searchable_text(check))) or None
    )
    session.add(check)
    session.commit()
    return check


def author_url(platform: str, handle: str) -> str:
    handle = handle.lstrip("@")
    if platform.startswith("tiktok"):
        return f"https://www.tiktok.com/@{handle}"
    return f"https://www.douyin.com/user/{handle}"


def check_youtube(
    targets: list[Target], caller: "object | None" = None
) -> dict[str, FetchResult]:
    """Re-check YouTube by id lookup rather than by reading a page.

    The API answers with the videos that still exist, so the ones
    missing from the answer are the ones that no longer resolve. That
    removes the whole class of error the HTML path has to guard
    against: there is no wording to keep up to date, and no removed
    video answering 200. A failed call raises, so it can never look
    like a removal.

    The result is expressed as FetchResult so one code path records and
    classifies every platform.
    """
    from . import youtube

    kwargs = {"caller": caller} if caller is not None else {}
    ids = [target.video_id for target in targets]
    alive, statuses = youtube.existing_ids(ids, **kwargs)  # type: ignore[arg-type]

    out: dict[str, FetchResult] = {}
    for video_id in ids:
        if video_id not in alive:
            # The id resolves to nothing. Phrased as the API's own
            # answer, not as a page that said so.
            out[video_id] = FetchResult(
                status=404,
                final_url=youtube.watch_url(video_id),
                body="youtube api: id not returned",
            )
            continue
        status = statuses.get(video_id, "unknown")
        body = f"youtube api: privacyStatus={status}"
        if status in ("private", "privacyStatusUnspecified"):
            body += " this account is private"
        out[video_id] = FetchResult(
            status=200, final_url=youtube.watch_url(video_id), body=body
        )
    return out


def run_round(
    session: Session,
    fetcher: Fetcher = fetch,
    now: datetime | None = None,
    limit: int | None = None,
    pause_seconds: float = 2.0,
    targets: Iterable[Target] | None = None,
    ignore_cadence: bool = False,
    skip_gone: bool = False,
    youtube_checker: Callable[[list[Target]], dict[str, FetchResult]] | None = check_youtube,
) -> RecheckReport:
    """Check everything due once, recording each response.

    The pause is deliberate and the default is not zero: a study that
    gets itself blocked partway through has lost observations it cannot
    go back for -- the videos it was measuring may be gone by the time
    access returns.
    """
    moment = now or _utcnow()
    report = RecheckReport()
    if ignore_cadence:
        due = list(targets) if targets is not None else collected_targets(session)
    else:
        due = due_targets(session, moment, targets, skip_gone=skip_gone)
    if limit is not None:
        due = due[:limit]

    # YouTube is looked up fifty ids at a time, so it is resolved in
    # one pass before the per-target loop rather than one request per
    # video like the platforms that have to be read as pages.
    api_results: dict[str, FetchResult] = {}
    api_targets = [target for target in due if target.platform == "youtube"]
    if api_targets and youtube_checker is not None:
        api_results = youtube_checker(api_targets)

    for index, target in enumerate(due):
        from_api = api_results.get(target.video_id) if target.platform == "youtube" else None
        if from_api is None:
            if index and pause_seconds:
                time.sleep(pause_seconds)
            result = fetcher(target.url)
        else:
            result = from_api

        check = _record(session, target, "video", target.url, result, moment)
        verdict = classify(check)
        report.record(verdict)

        # Only then, and only when it would distinguish something: if
        # the video is missing, whether the account is still there is
        # what separates one removal from a whole account disappearing.
        if (
            verdict in (GONE, WITHHELD, UNKNOWN)
            and target.author_handle
            and target.platform != "youtube"
        ):
            if pause_seconds:
                time.sleep(pause_seconds)
            url = author_url(target.platform, target.author_handle)
            _record(session, target, "author", url, fetcher(url), moment)

    return report


def main() -> None:  # pragma: no cover - thin CLI wrapper
    import argparse

    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description="Re-check collected video links.")
    parser.add_argument("--limit", type=int, default=None, help="stop after N videos")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between requests")
    parser.add_argument(
        "--all",
        action="store_true",
        help="check every collected link, ignoring the cadence",
    )
    parser.add_argument(
        "--skip-gone",
        action="store_true",
        help=(
            "leave out videos already found gone -- saves little, and a "
            "removal that gets reversed then goes unseen"
        ),
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        print(
            run_round(
                session,
                limit=args.limit,
                pause_seconds=args.pause,
                ignore_cadence=args.all,
                skip_gone=args.skip_gone,
            )
        )


if __name__ == "__main__":  # pragma: no cover
    main()
