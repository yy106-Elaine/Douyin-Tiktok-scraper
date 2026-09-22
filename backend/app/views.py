"""One row per video, however its identity arrived.

A post read off the screen and a link copied out of the share sheet are
two halves of the same observation: the screen has the caption and the
counts, the link has the id. They were stored separately and shown
separately, which left the dashboard asking the reader to join them by
eye. Everything a study needs about one video belongs on one row.

So this assembles that row. Captured posts supply most of them;
a shared link that has not been paired to any post gets a row of its
own rather than a second table, because an unpaired link is still a
video to re-check and hiding it in a separate section is how it gets
forgotten.

Publication time is chosen here too, best source first, and the source
is reported alongside the value -- see `posted_source`.
"""
from __future__ import annotations

import re

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import local, local_date, start_of_local_day
from .links import describe, extract
from .models import SharedLink, WebAuthor, WebVideo
from .platforms import API_PLATFORMS
from .platforms import filter_policy
from .relevance import (
    FICTION_STRATUM,
    HIDDEN,
    classify,
)
from .parsers import PLATFORM_TABLES
from .snowflake import posted_at_from_video_id

#: A post whose id came from a link the device harvested for that exact
#: capture. The association is a fact, not an inference.
LINKED_EXACT = "linked (exact)"
#: A post whose id came from a link matched on time alone. Weaker, and
#: named so an analysis can exclude these rows.
LINKED_BY_TIME = "linked (by time)"
#: A post whose id was already on screen -- no link needed.
ID_ON_SCREEN = "id on screen"
#: A post row with no id yet: captured, but nothing to re-check with.
NO_LINK = "no link yet"
#: A copied link that resolved to an id but matched no captured post.
LINK_ONLY = "link only"
#: A copied short link that has not been followed to its real id yet.
NEEDS_RESOLVING = "needs resolving"
#: The row's fields came from the video's own page, fetched by id.
FROM_PAGE = "read from the page"


@dataclass(frozen=True)
class VideoRow:
    """Everything known about one video, from either source."""

    when: datetime
    participant_id: str
    platform: str
    state: str

    posted_at: datetime | None
    posted_display: str | None
    #: Where `posted_display` came from: "video id" (exact, decoded
    #: from the id), "api" (exact, the platform said so), "screen"
    #: (parsed from what the interface rendered), or "as shown" (the
    #: rendered string, unparsed). Empty when unknown.
    posted_source: str

    video_id: str | None
    video_url: str | None
    author_handle: str | None
    author_name: str | None
    caption: str | None
    feed: str | None

    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    save_count: int | None = None

    counts_approximate: bool = False
    is_ad: bool | None = None
    is_ai_generated: bool | None = None

    #: Null when in scope; otherwise why the row is out. See
    #: app/relevance.py.
    relevance: str | None = None

    #: How many collected rows this one stands for. Above one when the
    #: same post was copied repeatedly -- see `_collapse_repeats`.
    repeats: int = 1


def publication(
    video_id: object,
    posted_on: datetime | None,
    posted_at_raw: str | None,
    platform: str | None = None,
) -> tuple[datetime | None, str | None, str]:
    """Best available publication time, with its provenance.

    The id decodes to the second and needs nothing from the interface,
    so it wins wherever it exists. What the screen showed is the
    fallback, and the unparsed string is better than an empty column.

    `platform` only changes the label: YouTube's `posted_on` came from
    its API and is exact, so calling it "from screen" would understate
    it as badly as calling a rendered "11h ago" exact would overstate
    the others.
    """
    derived = posted_at_from_video_id(video_id)
    if derived is not None:
        return derived, local(derived).strftime("%Y-%m-%d %H:%M"), "video id"
    if posted_on is not None:
        source = "api" if (platform or "").startswith("youtube") else "screen"
        return posted_on, local(posted_on).strftime("%Y-%m-%d %H:%M"), source
    if posted_at_raw:
        return None, posted_at_raw, "as shown"
    return None, None, ""


_STATE_BY_METHOD = {
    "fingerprint": LINKED_EXACT,
    "window": LINKED_BY_TIME,
}


def _post_state(post, method: str | None) -> str:
    if not post.video_id:
        return NO_LINK
    return _STATE_BY_METHOD.get(method or "", ID_ON_SCREEN)


def _row_from_post(post, platform: str, method: str | None = None) -> VideoRow:
    posted_at, display, source = publication(
        post.video_id, post.posted_on, post.posted_at_raw, platform
    )
    return VideoRow(
        when=post.captured_at,
        participant_id=post.participant_id,
        platform=platform,
        state=_post_state(post, method),
        posted_at=posted_at,
        posted_display=display,
        posted_source=source,
        video_id=post.video_id,
        video_url=post.video_url,
        author_handle=post.author_handle,
        author_name=post.author_name,
        caption=post.caption,
        feed=post.feed,
        like_count=post.like_count,
        comment_count=post.comment_count,
        share_count=post.share_count,
        save_count=post.save_count,
        counts_approximate=bool(post.counts_approximate),
        is_ad=post.is_ad,
        is_ai_generated=post.is_ai_generated,
        relevance=post.relevance,
    )


def _row_from_link(link: SharedLink) -> VideoRow:
    posted_at, display, source = publication(link.video_id, None, None)
    # Before it is resolved a link has no canonical URL, only the short
    # one sitting inside the text that was copied. That one still opens
    # the video, which is what the row is for.
    target = link.canonical_url or extract(link.raw_text).raw_url
    # The blob the share sheet produced names the author and quotes
    # the caption. These rows showed neither for a while, on the
    # reasoning that no post had been matched -- but the text a person
    # copied is itself an observation, and it is the only one these
    # rows have.
    said = describe(link.raw_text)
    # The handle is read off the URL, where TikTok puts it, and
    # nowhere else. Douyin's is the 抖音号 and lives on the author's
    # profile; a value attached to the link afterwards -- by the
    # device's own profile visits, matched on time -- turned out to
    # be the neighbouring author's as often as this one's, so it is
    # not read back. A name in the handle column is worse than an
    # empty one.
    from_url = extract(link.canonical_url or link.raw_text)
    return VideoRow(
        when=link.shared_at,
        participant_id=link.participant_id,
        platform=link.platform,
        state=LINK_ONLY if link.video_id else NEEDS_RESOLVING,
        posted_at=posted_at,
        posted_display=display,
        posted_source=source,
        video_id=link.video_id,
        video_url=target,
        author_handle=from_url.author_handle,
        author_name=said.author_name,
        caption=said.caption,
        feed=None,
        # Marked here, because nothing else will.
        #
        # The corpus filter runs as a SQL condition over the post
        # tables, and a link that never paired to a post has no row
        # there -- so these bypassed it entirely. That was invisible
        # while the default listing was post-shaped; once it became
        # one row per link, the filter was reaching almost nothing on
        # the phone platforms. A Douyin rule written to exclude
        # captions like LWL出游随拍记录 re-marked none of them, because
        # every one of them was on a link row.
        #
        # Only where there is text to read. A link whose share blob
        # carried no caption says nothing about its topic, and
        # `classify("")` answers "no text" -- which is an exclusion.
        # Applied here that would have hidden every unresolved link,
        # which is precisely the work the page exists to report.
        relevance=(
            classify(said.caption, policy=filter_policy(link.platform))
            if said.caption
            else None
        ),
    )


#: What `show` may ask for beyond a specific exclusion reason.
SHOW_ALL = "all"
SHOW_EXCLUDED = "excluded"
#: The two strata inside the corpus. Scripted drama is in scope and is
#: tracked, but it is not the population the interviews are about, so
#: it is read -- and its takedown rate quoted -- separately. See
#: `app.relevance.FICTION_STRATUM`.
SHOW_FICTION = "fiction only"
SHOW_FIRSTHAND = "firsthand"
#: The rows with no video id, which the default view leaves out.
#:
#: One link is one video, deliberately copied, with an id that can be
#: re-checked. A screen reading with no link is an observation of
#: something the phone saw; until a link or a page attaches an id to
#: it, it is not a video the study can follow.
#:
#: They used to be listed together, and on TikTok that made 85 rows
#: out of 25 links and 60 screen readings -- the same videos, twice,
#: with nothing saying which half belonged to which. Pairing them by
#: time was what put one video's handle beside another's caption, so
#: the answer is not to guess again but to count links as links and
#: fetch the content by id, which needs no guess at all.
SHOW_SCREEN_ONLY = "screen only"


def in_scope_filter(model, platform: str):
    """The corpus condition, for any query against a post table.

    One definition because there are two callers -- the dashboard and
    the CSV export -- and they had already drifted: the export was
    dropping hand-collected rows the dashboard kept.

    A phone row with an id is one whose link a person copied by hand,
    one video at a time. Its caption is often truncated to "...more"
    or absent, so the text is no evidence about the video, and these
    are the rows that cost the most to collect. YouTube gets no such
    exemption: the API chose those results.
    """
    condition = model.relevance.notin_(HIDDEN) | model.relevance.is_(None)
    if platform not in API_PLATFORMS:
        condition = condition | model.video_id.isnot(None)
    return condition


def _identity(model):
    """What counts as one video, for a distinct count.

    The video id where there is one. Otherwise the capture
    fingerprint, because a phone post with no copied link is still the
    same post when it is seen again the next day -- the phone
    platforms deliberately store one observation per post per day, so
    counting rows there would count days, not videos.
    """
    from sqlalchemy import func

    from .models import CaptureEvent

    return func.coalesce(model.video_id, CaptureEvent.fingerprint)


#: How many rows a whole-corpus count will look at. Larger than any
#: real corpus here; a cap at all is so a runaway table cannot hang
#: the page.
CORPUS_CAP = 10_000


def corpus(session: Session, platform: str, cap: int = CORPUS_CAP) -> list[VideoRow]:
    """Every distinct in-scope video on this platform, once each.

    The one population the page describes. It was two: the tiles
    counted rows in the post tables while the table under them
    listed merged rows, so a page could say `In the corpus 62` above
    a table of 85 -- two answers to one question, side by side, and
    neither of them the number of rows a reader could see.

    Merged, so a video reached by a link and by a screen reading is
    one video; filtered, so it is the corpus rather than everything
    collected; and computed once per page, because a second
    implementation is how the two drifted apart in the first place.

    This is both halves. The headline counts take `joined` of it --
    a screen reading with no link is not a distinct video, and
    adding those back was the second wrong answer to this question.
    """
    return video_rows(session, platform, limit=cap)


def strata(rows: list[VideoRow]) -> tuple[int, int]:
    """The corpus's two strata, over the rows the page lists.

    Counted from the same merged population as every other number on
    the page rather than from the post table. Counted there, the two
    chips read `firsthand 60` and `scripted drama 2` under a corpus
    of 85 -- the 62 that started this whole correction, still on the
    page in another place.

    Scripted drama is in scope and is tracked; it just has no author
    to interview, so it is reported apart. See
    `app.relevance.FICTION_STRATUM`.
    """
    firsthand = sum(1 for row in rows if _listed(row.relevance, SHOW_FIRSTHAND))
    fiction = sum(1 for row in rows if _listed(row.relevance, SHOW_FICTION))
    return firsthand, fiction


def first_seen(session: Session, platform: str) -> dict[str, datetime]:
    """Earliest observation of each distinct video in scope.

    Both counts below are about *new* videos, so both need first
    observation rather than any observation. Filtering rows by time
    instead would make a phone post seen every day look new every day
    -- the phone platforms store one observation per post per day on
    purpose.
    """
    from .models import CaptureEvent

    registered = PLATFORM_TABLES.get(platform)
    if registered is None:
        return {}
    model, _ = registered

    earliest: dict[str, datetime] = {}
    for identity, captured_at in session.execute(
        select(_identity(model), model.captured_at)
        .select_from(model)
        .join(CaptureEvent, CaptureEvent.id == model.capture_event_id)
        .where(in_scope_filter(model, platform))
    ):
        if identity is None:
            continue
        if identity not in earliest or captured_at < earliest[identity]:
            earliest[identity] = captured_at
    return earliest


def unique_in_scope(
    session: Session,
    platform: str,
    since: datetime | None = None,
    rows: list[VideoRow] | None = None,
) -> int:
    """Distinct videos in scope, or those first seen since `since`.

    Over the same merged population the table lists -- see [corpus].
    `rows` lets a page compute that population once and ask several
    questions of it.
    """
    held = corpus(session, platform) if rows is None else rows
    if since is None:
        return len(held)
    return sum(1 for row in held if row.when >= since)


def daily_counts(
    session: Session,
    platform: str,
    days: int = 7,
    now: datetime | None = None,
    rows: list[VideoRow] | None = None,
) -> list[tuple[str, int]]:
    """Distinct in-scope videos first collected on each of the last `days`."""
    moment = now or datetime.utcnow()
    # Days are the researcher's, not UTC's. An evening collection run
    # in Eastern time is already tomorrow in UTC, which put a day's
    # work under the next date and left the day it happened on
    # reading zero. See app/clock.py.
    last = local_date(moment)
    first = last - timedelta(days=days - 1)
    start = start_of_local_day(first)

    held = corpus(session, platform) if rows is None else rows
    counts: dict[str, int] = {}
    for captured_at in (row.when for row in held):
        if captured_at >= start:
            key = local_date(captured_at).isoformat()
            counts[key] = counts.get(key, 0) + 1

    return [
        ((first + timedelta(days=offset)).isoformat(),
         counts.get((first + timedelta(days=offset)).isoformat(), 0))
        for offset in range(days)
    ]


def video_rows(
    session: Session,
    platform: str,
    limit: int,
    show: str = "",
    with_id: bool | None = None,
) -> list[VideoRow]:
    """Merged rows for one platform, most recently seen first.

    `show` selects what to list: "" for the rows in scope, "all" for
    everything, "excluded" for only the hidden rows, or one exclusion
    reason to review that category on its own. Reviewing by category is
    the point -- a filter is only worth trusting once someone has read
    what it removed, and reading 500 mixed rows is not reading.

    `with_id` asks for one side of a different split: True for the
    videos the study can follow, False for the screen readings that
    have nothing to follow, None for both. See `SHOW_SCREEN_ONLY`.

    "Can follow" is not "has an id". A link copied and not yet
    resolved has no id and is still a link -- hiding it would hide
    work waiting to be done -- and a row whose id was read off the
    screen has no link and is still followable. So the test is: an id,
    or a link, or both.

    `limit` bounds the rows returned, not the rows read. Bounding the
    query instead is what made a table headed `one row per link 93`
    end at 79: the phone stores one observation per post per day, so
    six days of collection is several times as many post rows as
    videos, and taking the newest 200 of those before merging simply
    dropped the videos whose most recent sighting fell outside them.
    The cut has to come after the merge, or it cuts observations
    while appearing to cut videos.
    """
    registered = PLATFORM_TABLES.get(platform)
    if registered is None:
        return []
    model, _ = registered

    # How each paired link was matched, so a row can say whether its id
    # is a fact or a nearest-in-time guess.
    methods = {
        capture_id: method
        for capture_id, method in session.execute(
            select(SharedLink.matched_capture_id, SharedLink.pairing_method).where(
                SharedLink.matched_capture_id.isnot(None)
            )
        )
    }

    statement = select(model).order_by(model.captured_at.desc())
    in_scope = in_scope_filter(model, platform)

    if show == SHOW_ALL:
        pass
    elif show == SHOW_EXCLUDED:
        statement = statement.where(~in_scope)
    elif show == SHOW_FICTION:
        statement = statement.where(in_scope, model.relevance == FICTION_STRATUM)
    elif show == SHOW_FIRSTHAND:
        statement = statement.where(
            in_scope,
            (model.relevance != FICTION_STRATUM) | model.relevance.is_(None),
        )
    elif show:
        # One named reason. Still intersected with the carve-out, so a
        # hand-collected row never appears as excluded when it is not.
        statement = statement.where(model.relevance == show, ~in_scope)
    else:
        statement = statement.where(in_scope)
    rows = [
        _row_from_post(post, platform, methods.get(post.capture_event_id))
        for post in session.scalars(statement.limit(CORPUS_CAP))
    ]

    # Only the links that no post row already accounts for: a paired
    # link's id is on its post's row, and showing it twice is the
    # duplication this module exists to remove.
    unpaired = session.scalars(
        select(SharedLink)
        .where(
            SharedLink.platform == platform,
            SharedLink.matched_capture_id.is_(None),
        )
        .order_by(SharedLink.shared_at.desc())
        .limit(CORPUS_CAP)
    )
    rows.extend(_row_from_link(link) for link in unpaired)

    # Merged newest-sighting-first, so the row kept as the base of a
    # merge is the most recent reading of that video.
    rows.sort(key=lambda row: row.when, reverse=True)
    merged = _with_page_facts(session, _collapse_repeats(_one_row_per_video(rows)))
    merged = _in_or_out(merged, show, filter_policy(platform))
    if with_id is not None:
        merged = [row for row in merged if _followable(row) is with_id]
    return _newest_first(merged)[:limit]


def _in_or_out(rows: list[VideoRow], show: str, policy: str) -> list[VideoRow]:
    """Apply the corpus filter to the rows SQL could not reach.

    The filter is a condition over the post tables, so a link that
    never paired to a post was never subject to it, and a caption the
    video's own page supplied was never re-read against it. Both were
    invisible while the listing was post-shaped. Once it became one
    row per link, the filter was reaching almost nothing on the phone
    platforms: a Douyin rule written to exclude captions like
    LWL出游随拍记录 re-marked none of them, because every one of them
    was on a link row.

    Post rows keep the reason stored against them -- it was computed
    from the caption and the description together, and recomputing
    from the caption alone would lose half the evidence. What is
    recomputed is a row whose caption arrived after that marking: the
    page's caption is the fuller one, and the whole point of fetching
    it was that it is the authority.

    The hand-collected carve-out is applied here too -- see
    `in_scope_filter`, which carries it in SQL. It had been left out,
    which nothing showed while every TikTok caption passed anyway;
    the moment the TikTok rule started asking something of the text,
    a row a person had chosen by hand could be hidden on a caption
    the interface had cut off mid-word.
    """
    out = []
    for row in rows:
        reason = row.relevance
        if row.caption and (reason is None or row.state == FROM_PAGE):
            reason = classify(row.caption, policy=policy)
        if reason in HIDDEN and _chosen_by_hand(row) and _cut_off(row.caption):
            reason = None
        if _listed(reason, show):
            out.append(replace(row, relevance=reason))
    return out


#: What the interface leaves behind when it truncates a caption.
_CUT_OFF = re.compile(r"(?:\.\.\.|\u2026)\s*(?:more|展开|展開)?\s*$", re.IGNORECASE)


def _cut_off(caption: str | None) -> bool:
    """Whether this caption is the interface's truncation of one.

    The carve-out is for text that is *no evidence*, which is a
    narrower thing than text that fails the rule. A caption ending in
    "...more" was cut off mid-sentence by the app and says nothing
    about what the rest of it contained. A complete caption that
    simply does not mention the topic is evidence, and it is the
    evidence the rule was written to read -- the Douyin captions that
    came back from a #lwl search with no tag in them (上班容易吗,
    出海打鱼) are complete, and excluding them was a decision, not an
    accident.

    A caption absent altogether is deliberately not covered. Those
    rows carry `no text`, they are counted under their own reason,
    and whether a video with nothing readable belongs in a corpus
    defined by its text is a question for the study, not for this
    function to answer quietly.
    """
    if not caption:
        return False
    return bool(_CUT_OFF.search(caption.strip()))


def _chosen_by_hand(row: VideoRow) -> bool:
    """A phone row someone copied the link of, one video at a time.

    These cost the most to collect and the text is the least
    trustworthy thing about them. YouTube gets no exemption: the API
    chose those results, nobody did.
    """
    return bool(row.video_id) and row.platform not in API_PLATFORMS


def _listed(reason: str | None, show: str) -> bool:
    """Whether a row with this reason belongs in this listing."""
    hidden = reason in HIDDEN
    if show == SHOW_ALL:
        return True
    if show == SHOW_EXCLUDED:
        return hidden
    if show == SHOW_FICTION:
        return not hidden and reason == FICTION_STRATUM
    if show == SHOW_FIRSTHAND:
        return not hidden and reason != FICTION_STRATUM
    if show:
        return reason == show
    return not hidden


def _followable(row: VideoRow) -> bool:
    """Whether this row is a video the study can go back to.

    An id, or a link that will give one. Everything else is a reading
    of something the phone had on screen, which may well be a real
    video -- it just cannot be re-checked, exported with a URL, or
    fetched by id, so it is not one row of the corpus yet.
    """
    return bool(row.video_id) or row.state != NO_LINK


def joined(rows: list[VideoRow]) -> list[VideoRow]:
    """The rows that are known to be one distinct video each.

    A row with an id -- or a link that will give one -- is a video
    the study can go back to: re-checked, fetched, downloaded, and
    its author written to. Two such rows carrying the same id are
    merged before this, so counting them counts videos.

    A screen reading with no link is not. Nothing joins it to
    anything: it may be one of the linked videos seen again, or the
    same video read twice under two slightly different captions, and
    there is no way to tell. Adding those to the linked rows is how
    25 links and 60 readings became "85 videos" -- the arithmetic
    the table's one-row-per-link default was introduced to stop, and
    which then reappeared in the tile above it.

    So they are counted, reachable by their own chip, and reported
    beside the corpus rather than inside it. Fetch-by-id is what
    turns one into a corpus row, and until it has run the honest
    number is the smaller one.
    """
    return [row for row in rows if _followable(row)]


def id_counts(
    session: Session,
    platform: str,
    cap: int = CORPUS_CAP,
    rows: list[VideoRow] | None = None,
) -> tuple[int, int]:
    """In-scope rows (with an id, without one), after merging.

    Counted through the same merge the table uses, because the answer
    has to be the number of rows the other view would show -- two
    separately-written counts is how the dashboard and the export
    drifted apart before.
    """
    held = corpus(session, platform, cap) if rows is None else rows
    linked = len(joined(held))
    return linked, len(held) - linked


@dataclass(frozen=True)
class Spread:
    """How many accounts the corpus is drawn from, and how evenly.

    A takedown rate is a rate for whoever is in the sample. One
    TikTok search for `Chinese lesbian` returned 26 videos from 12
    accounts, and 15 of them -- 58% -- were one account's: a prolific
    poster whose captions are numbered into the three hundreds and
    whose hashtags are the search term. That rate is substantially
    that account's rate, and a reader cannot tell unless the page
    says so.

    Counted, not acted on. Excluding the account was considered and
    rejected: a prolific poster of precisely the targeted content is
    more exposed to moderation, not less, so dropping it would bias
    the rate downward and hide the very removals the study exists to
    see. The honest handling is to report the concentration beside
    the rate, and to quote a rate without the dominant account as a
    sensitivity check -- both of which need this number and neither
    of which needs the data changed.
    """

    videos: int = 0
    accounts: int = 0
    top_handle: str | None = None
    top_videos: int = 0
    #: Whether `top_handle` is an identifier or only a display name.
    #: A display name printed as `@name` implies something the row
    #: does not have -- the mistake `_row_from_link` was fixed for --
    #: so the page checks this before naming the account at all.
    top_named: bool = False

    @property
    def top_share(self) -> float | None:
        """The largest account's share, or None when nothing is known."""
        if not self.videos:
            return None
        return self.top_videos / self.videos


def author_spread(
    session: Session,
    platform: str,
    cap: int = CORPUS_CAP,
    rows: list[VideoRow] | None = None,
) -> Spread:
    """The corpus's spread across accounts, over the rows on the page.

    Counted through the same merge the table uses, so the number is
    about the rows a reader can see. Rows with no author are left out
    rather than pooled under one "unknown" account, which would read
    as a thirteenth poster.
    """
    held = corpus(session, platform, cap) if rows is None else rows
    counts: dict[str, int] = {}
    # A display name identifies an account well enough to count it --
    # Douyin rows have no 抖音号 until a profile has been read, and
    # leaving them out would make the spread look wider than it is.
    named: set[str] = set()
    for row in held:
        handle = (row.author_handle or "").lstrip("@").strip()
        who = handle or (row.author_name or "").strip()
        if not who:
            continue
        counts[who] = counts.get(who, 0) + 1
        if handle:
            named.add(who)
    if not counts:
        return Spread()
    top_handle, top_videos = max(counts.items(), key=lambda pair: pair[1])
    return Spread(
        videos=sum(counts.values()),
        accounts=len(counts),
        top_handle=top_handle,
        top_videos=top_videos,
        top_named=top_handle in named,
    )


def _one_row_per_video(rows: list[VideoRow]) -> list[VideoRow]:
    """Collapse rows that a video id proves are the same video.

    A post is stored once per capture, and a caption that had not
    rendered yet makes the second capture look like a different post:
    the same author and the same counts under two identities, because
    identity falls back to author plus caption. Once a link has given
    both rows the same id, they are provably one video, and a table
    that lists it twice is a table nobody can count.

    Rows with no id are left alone. Without one there is no proof, and
    guessing that two rows are the same video would silently merge two
    videos by the same author -- a worse error than showing two rows.

    The kept row is the fullest, field by field, so a caption read on
    the second pass is not lost to a first pass that missed it.
    """
    at: dict[str, int] = {}
    out: list[VideoRow] = []
    for row in rows:
        if not row.video_id:
            out.append(row)
            continue
        index = at.get(row.video_id)
        if index is None:
            at[row.video_id] = len(out)
            out.append(row)
            continue
        held = out[index]
        out[index] = replace(
            _filled(held, row), repeats=held.repeats + row.repeats
        )

    return out


#: Filled from a second sighting when the first left them empty. Never
#: `when` or `video_id`: `when` is handled separately, because it is
#: the earliest of the sightings rather than either one's, and the id
#: is what proved the two are the same row.
_MERGEABLE = (
    "posted_at",
    "posted_display",
    "posted_source",
    "video_url",
    "author_handle",
    "author_name",
    "caption",
    "feed",
    "like_count",
    "comment_count",
    "share_count",
    "save_count",
    "is_ad",
    "is_ai_generated",
)


def _filled(held: VideoRow, other: VideoRow) -> VideoRow:
    """`held` with its empty fields taken from `other`. Rows are frozen.

    `when` becomes the earlier of the two. Rows arrive newest first,
    so keeping the held row's would have made every merged row report
    its most recent sighting as the moment it was seen -- and the
    counts of what is new in a day are built on this field. A video
    seen again today is not new today.
    """
    gaps = {}
    for field in _MERGEABLE:
        if getattr(held, field, None) in (None, ""):
            value = getattr(other, field, None)
            if value not in (None, ""):
                gaps[field] = value
    if other.when < held.when:
        gaps["when"] = other.when
    return replace(held, **gaps) if gaps else held


def _repeat_key(row: VideoRow) -> tuple[str, str] | None:
    """What makes two rows the same post when no id proves it.

    The author, and the head of the caption with its spacing removed.
    Both are needed: an author posts more than one video, and the
    captions are the only thing telling those apart.

    Spacing and length are normalised because the two sources write
    the same caption differently -- the screen renders `#短发 #lwl`
    and the share text writes `# 短发 # lwl`, and the share text
    truncates a long one with an ellipsis. Comparing a short head of
    the stripped text is what makes those meet.
    """
    # The leading @ is part of where the name was read, not part of
    # the name: the feed's title node renders `@恶魔钉（流量回家。）`
    # and the share text writes `【恶魔钉（流量回家。）的作品】`. One
    # character kept the two halves of 51 posts apart.
    author = (row.author_name or row.author_handle or "").lstrip("@").strip()
    caption = "".join((row.caption or "").split())
    if not author or not caption:
        return None
    return author, caption[:_HEAD]


#: Characters of caption compared. Long enough that two videos by one
#: author are not confused, short enough to survive the share text's
#: ellipsis.
_HEAD = 10


def _collapse_repeats(rows: list[VideoRow]) -> list[VideoRow]:
    """One row per post, where the author and caption say it is one.

    The loop copies the link of whatever video is on screen, and when
    a day's search results run out the feed stops advancing -- one
    run put the same post on screen eighty times, and the dashboard
    listed it eighty times. Each copy is a real observation and stays
    in the database; what a reader needs is the post, once, with the
    number of times it was seen.

    Rows an id has already merged come in as one; this is for the
    ones with no id yet, which is most of them until the links are
    followed. A row with no author or no caption is never folded --
    there is nothing there to be sure with.
    """
    at: dict[tuple[str, str], int] = {}
    out: list[VideoRow] = []
    for row in rows:
        key = _repeat_key(row)
        if key is None:
            out.append(row)
            continue
        index = at.get(key)
        if index is None:
            at[key] = len(out)
            out.append(row)
            continue
        held = out[index]
        if held.video_id and row.video_id and held.video_id != row.video_id:
            # Two ids are two videos, whatever the captions say. One
            # channel posting the same title twice is ordinary.
            out.append(row)
            continue
        out[index] = replace(
            _filled(held, row), repeats=held.repeats + row.repeats
        )
    return out


def fiction_ids(session: Session, platform: str) -> set[str]:
    """Video ids of the scripted-drama stratum, for splitting a rate.

    A `Finding` is built from the check history and carries no
    relevance, so the split has to be made from the post rows. See
    `app.relevance.FICTION_STRATUM` for why the two are reported apart.
    """
    registered = PLATFORM_TABLES.get(platform)
    if registered is None:
        return set()
    model, _ = registered
    return {
        video_id
        for (video_id,) in session.execute(
            select(model.video_id).where(
                model.video_id.isnot(None), model.relevance == FICTION_STRATUM
            )
        )
    }


def corpus_counts(
    session: Session,
    platform: str,
    cap: int = CORPUS_CAP,
    rows: list[VideoRow] | None = None,
) -> tuple[int, int]:
    """Videos on the page, and how many of them have an id.

    Counted over the merged rows rather than the post table. Once
    pairing became exact-only most ids live on link rows, so counting
    posts reported "8% with a video ID" for a page where every row
    showed one -- a tile disagreeing with the table under it.
    """
    held = corpus(session, platform, cap) if rows is None else rows
    return len(held), sum(1 for row in held if row.video_id)


def _newest_first(rows: list[VideoRow]) -> list[VideoRow]:
    """Newest publication first, and the undated afterwards.

    Publication is what the table is about -- when the video went up,
    not when this study happened to scroll past it -- so it is what
    the order should follow.

    Rows whose publication time is unknown are not sorted among the
    known ones on some stand-in: that would put a video collected an
    hour ago above one published today and read as a claim about
    when it was posted. They follow, ordered by when they were seen.
    """
    dated = [row for row in rows if row.posted_at is not None]
    undated = [row for row in rows if row.posted_at is None]
    dated.sort(key=lambda row: row.posted_at, reverse=True)
    undated.sort(key=lambda row: row.when, reverse=True)
    return dated + undated


@dataclass(frozen=True)
class PageFact:
    """What the video's own page said, for one video.

    The authority for these fields -- see `WebVideo`. Pulled out of
    `_with_page_facts` so the takedown table can use the same source
    as the capture table: those two disagreeing about who posted a
    video, or when, is worse than either of them being incomplete.
    """

    author_name: str | None = None
    author_handle: str | None = None
    caption: str | None = None
    posted_on: datetime | None = None


def page_facts(session: Session, video_ids) -> dict[str, PageFact]:
    """Page readings for these ids, keyed by id.

    The 抖音号 is looked up through the account rather than the video:
    it lives on the profile, and one visit answers it for everything
    that account posted.
    """
    wanted = {video_id for video_id in video_ids if video_id}
    if not wanted:
        return {}

    pages = {
        page.video_id: page
        for page in session.scalars(
            select(WebVideo).where(WebVideo.video_id.in_(wanted))
        )
    }
    if not pages:
        return {}

    handles = {
        author.sec_uid: author.author_handle
        for author in session.scalars(
            select(WebAuthor).where(
                WebAuthor.sec_uid.in_(
                    {page.sec_uid for page in pages.values() if page.sec_uid}
                )
            )
        )
        if author.author_handle
    }

    return {
        video_id: PageFact(
            author_name=page.author_name,
            author_handle=handles.get(page.sec_uid or "") or page.author_handle,
            caption=page.caption,
            posted_on=page.posted_on,
        )
        for video_id, page in pages.items()
    }


def _with_page_facts(session: Session, rows: list[VideoRow]) -> list[VideoRow]:
    """Let the video's own page overrule what the screen showed.

    Both are real observations, but they are not equally attached to
    the video. A page fetched by id belongs to that id by
    construction; a screen reading had to be stitched to a link
    afterwards, and that stitch is what produced one video's counts
    beside another's caption. So where a page has been read, it wins,
    and the row says where its fields came from.

    The 抖音号 comes from the author's profile, keyed on the account
    rather than the video: one visit answers it for everything that
    account posted.
    """
    facts = page_facts(session, (row.video_id for row in rows))
    if not facts:
        return rows

    pages = {
        page.video_id: page
        for page in session.scalars(
            select(WebVideo).where(WebVideo.video_id.in_(facts))
        )
    }

    out: list[VideoRow] = []
    for row in rows:
        page = pages.get(row.video_id or "")
        if page is None:
            out.append(row)
            continue

        posted_at = page.posted_on or row.posted_at
        out.append(
            replace(
                row,
                state=FROM_PAGE,
                posted_at=posted_at,
                posted_display=(
                    local(posted_at).strftime("%Y-%m-%d %H:%M") if posted_at else None
                ),
                posted_source="page" if page.posted_on else row.posted_source,
                author_name=page.author_name or row.author_name,
                author_handle=(
                    facts[row.video_id or ""].author_handle or row.author_handle
                ),
                caption=page.caption or row.caption,
                like_count=_prefer(page.like_count, row.like_count),
                comment_count=_prefer(page.comment_count, row.comment_count),
                share_count=_prefer(page.share_count, row.share_count),
                save_count=_prefer(page.collect_count, row.save_count),
                # The page gives exact numbers; the screen abbreviated
                # them, and that caveat does not carry over.
                counts_approximate=(
                    False if page.like_count is not None else row.counts_approximate
                ),
            )
        )
    return out


def _prefer(from_page: int | None, from_screen: int | None) -> int | None:
    return from_page if from_page is not None else from_screen
