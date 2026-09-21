"""A read-only web view of what has been collected.

Server-rendered HTML with no build step and no JavaScript: the point is
to be able to open it on a phone during a collection run and see
whether data is actually arriving.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import is_admin_key
from .clock import local
from .config import settings
from .db import get_session
from .models import CaptureEvent, SharedLink
from .parsers import PLATFORM_TABLES
from .platforms import filter_policy
from .recheck import ALIVE, AUTHOR_GONE, GONE, WITHHELD, collected_targets, due_targets
from .relevance import FICTION_STRATUM, HIDDEN
from .snowflake import derivation_is_verified
from .survival import Finding, findings, summarise
from .views import (
    FROM_PAGE,
    corpus_counts,
    daily_counts,
    fiction_ids,
    in_scope_filter,
    unique_in_scope,
    ID_ON_SCREEN,
    LINK_ONLY,
    LINKED_BY_TIME,
    NEEDS_RESOLVING,
    NO_LINK,
    VideoRow,
    video_rows,
)

router = APIRouter()

_ROW_LIMIT = 200


def require_admin_view(request: Request, key: str = Query(default="")) -> str:
    """Admin auth that a browser can satisfy.

    A browser cannot set a header by typing a URL, so the key may also
    arrive as `?key=...`. That puts it in history and server logs, so
    only serve this behind TLS and treat the URL as a credential.
    """
    candidate = request.headers.get("x-api-key") or key
    if not candidate or not is_admin_key(candidate):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="pass the admin key as ?key=... or an X-API-Key header",
        )
    return candidate


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    key: str = Depends(require_admin_view),
    platform: str = Query(default="douyin"),
    show: str = Query(default="", description="'all' also lists filtered rows"),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if platform not in PLATFORM_TABLES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown platform {platform}"
        )
    model, _ = PLATFORM_TABLES[platform]

    # Over the rows the page actually shows, not over the post table:
    # with exact-only pairing most ids sit on link rows.
    posts, with_id = corpus_counts(session, platform)
    approximate = (
        session.scalar(
            select(func.count()).select_from(model).where(model.counts_approximate.is_(True))
        )
        or 0
    )
    events = session.scalar(select(func.count()).select_from(CaptureEvent)) or 0

    # Links whose short form has never been followed. This is the one
    # number on the page that asks for an action, so it is a tile.
    unresolved = (
        session.scalar(
            select(func.count())
            .select_from(SharedLink)
            .where(SharedLink.platform == platform, SharedLink.video_id.is_(None))
        )
        or 0
    )

    # Every exclusion reason with a count, so the filter is reviewable
    # category by category rather than as one number to trust.
    # The corpus's two strata. Counted here rather than from `rows`,
    # which is capped at _ROW_LIMIT.
    in_corpus = in_scope_filter(model, platform)
    fiction = (
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(in_corpus, model.relevance == FICTION_STRATUM)
        )
        or 0
    )
    firsthand = (
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(
                in_corpus,
                (model.relevance != FICTION_STRATUM) | model.relevance.is_(None),
            )
        )
        or 0
    )

    reasons = {
        reason: count
        for reason, count in session.execute(
            select(model.relevance, func.count())
            .where(model.relevance.in_(HIDDEN))
            .group_by(model.relevance)
        )
    }
    filtered = sum(reasons.values())

    rows = video_rows(session, platform, _ROW_LIMIT, show)
    dated = sum(1 for row in rows if row.posted_display)

    # Distinct videos in scope, not rows: the phone platforms store one
    # observation per post per day, so a row count there counts days.
    now = datetime.utcnow()
    unique = unique_in_scope(session, platform)
    day = unique_in_scope(session, platform, now - timedelta(hours=24))
    three = unique_in_scope(session, platform, now - timedelta(days=3))
    per_day = daily_counts(session, platform, days=7, now=now)

    return HTMLResponse(
        _page(
            key=key,
            platform=platform,
            posts=posts,
            with_id=with_id,
            approximate=approximate,
            events=events,
            unresolved=unresolved,
            rows=rows,
            dated=dated,
            filtered=filtered,
            reasons=reasons,
            fiction=fiction,
            firsthand=firsthand,
            show=show,
            unique=unique,
            day=day,
            three=three,
            per_day=per_day,
        )
    )


def _pct(part: int, whole: int) -> str:
    return "—" if not whole else f"{round(100 * part / whole)}%"


def _compact(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 10_000:
        return f"{value / 1_000:.1f}K".replace(".0K", "K")
    return f"{value:,}"


def _tile(label: str, value: str, note: str = "", raw_note: bool = False) -> str:
    text = note if raw_note else escape(note)
    note_html = f'<div class="note">{text}</div>' if note else ""
    return (
        '<div class="tile">'
        f'<div class="label">{escape(label)}</div>'
        f'<div class="value">{escape(value)}</div>'
        f"{note_html}</div>"
    )


def _cell(value: object) -> str:
    if value is None or value == "":
        return '<td class="muted">—</td>'
    return f"<td>{escape(str(value))}</td>"


def _num(value: object) -> str:
    if value is None:
        return '<td class="n muted">—</td>'
    return f'<td class="n">{escape(_compact(int(value)))}</td>'


#: Colour carries how much a row's identity can be trusted: green for
#: an exact match, amber for anything inferred or still pending.
_STATE_CLASS = {
    FROM_PAGE: "good",
    NEEDS_RESOLVING: "warn",
    LINKED_BY_TIME: "warn",
    LINK_ONLY: "crit",
    NO_LINK: "muted",
    ID_ON_SCREEN: "good",
}

_COLUMNS = 12


def _posted_cell(row: VideoRow) -> str:
    """The publication time, with where it came from underneath.

    The provenance is on the row rather than in a footnote because the
    two sources are not interchangeable: one is exact to the second,
    the other is whatever the interface rounded it to.
    """
    if not row.posted_display:
        return '<td class="muted">&mdash;</td>'
    note = ""
    if row.posted_source == "video id":
        label = "from id" if derivation_is_verified(row.platform) else "from id?"
        note = f'<div class="prov exact">{label}</div>'
    elif row.posted_source == "page":
        note = '<div class="prov exact">from the page</div>'
    elif row.posted_source == "screen":
        note = '<div class="prov">from screen</div>'
    elif row.posted_source == "as shown":
        note = '<div class="prov">as shown</div>'
    return f'<td class="when">{escape(row.posted_display)}{note}</td>'


def _id_cell(row: VideoRow) -> str:
    if not row.video_id:
        # An unresolved short link has no id yet, but it does open.
        # It used to read "short link", which told the reader nothing
        # and made every unresolved row look alike -- the link itself
        # distinguishes them, and it is what gets pasted into a
        # notebook or handed to a collaborator.
        if row.video_url:
            return (
                f'<td class="vid"><a href="{escape(row.video_url)}" '
                'rel="noreferrer noopener" target="_blank">'
                f'{escape(_bare(row.video_url))}</a></td>'
            )
        return '<td class="muted">&mdash;</td>'
    if row.video_url:
        return (
            f'<td class="vid"><a href="{escape(row.video_url)}" '
            f'rel="noreferrer noopener" target="_blank">{escape(row.video_id)}</a></td>'
        )
    return f'<td class="vid">{escape(row.video_id)}</td>'


def _bare(url: str) -> str:
    """A URL without the scheme, which is the same on every row."""
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):].rstrip("/")
    return url.rstrip("/")


def _handle_cell(row: VideoRow) -> str:
    """The @handle, when there is one worth showing.

    On Douyin the handle is the 抖音号, and reading it means opening
    the author's profile -- which the assisted loop does not do. What
    the feed offers instead is the display name, which the parser
    stores in both columns, so the table printed it twice and implied
    an identifier it does not have. A name is not a handle.
    """
    handle = (row.author_handle or "").lstrip("@").strip()
    name = (row.author_name or "").lstrip("@").strip()
    if not handle or handle == name:
        return '<td class="muted">&mdash;</td>'
    return _cell(handle)


def _notes_cell(row: VideoRow) -> str:
    notes = [
        f'<span class="flag {_STATE_CLASS.get(row.state, "good")}">'
        f"{escape(row.state)}</span>"
    ]
    if row.repeats > 1:
        # The same post, copied this many times. Each copy is a real
        # observation and is still in the database; the reader needs
        # the post once.
        notes.append(f'<span class="flag muted">&times;{row.repeats} seen</span>')
    if row.counts_approximate:
        notes.append('<span class="flag approx">&asymp; approximate</span>')
    if row.is_ad:
        notes.append('<span class="flag ad">&#9650; ad</span>')
    if row.is_ai_generated:
        notes.append('<span class="flag ai">&#9670; AI</span>')
    return f'<td>{"".join(notes)}</td>'


def _video_rows(rows) -> str:
    if not rows:
        return (
            f'<tr><td colspan="{_COLUMNS}" class="empty">'
            "Nothing captured for this platform yet.</td></tr>"
        )

    out = []
    for number, row in enumerate(rows, start=1):
        out.append(
            "<tr>"
            f'<td class="rank">{number}</td>'
            f"{_posted_cell(row)}"
            f"{_id_cell(row)}"
            f"{_handle_cell(row)}"
            f"{_cell(row.author_name)}"
            f'<td class="caption">{escape((row.caption or "—")[:110])}</td>'
            f"<td class=\"when\">{escape(local(row.when).strftime('%m-%d %H:%M'))}</td>"
            f"{_num(row.like_count)}{_num(row.comment_count)}{_num(row.share_count)}"
            f"{_notes_cell(row)}"
            f"{_cell(row.feed)}"
            "</tr>"
        )
    return "".join(out)



_VIEWS = (
    ("Capture", "/dashboard"),
    ("Takedowns", "/dashboard/takedowns"),
    ("Overview", "/dashboard/overview"),
)


def _nav(view: str, platform: str | None, key: str) -> str:
    """The view, then the platform, as one strip of links.

    One row, in the same order, on every page. It was two rows, and
    Overview hid the platform half; both meant the strip moved or
    changed shape when the page changed, so a link was never where it
    had just been. On Overview the platform links lead to Capture,
    which is where one platform's own rows are.
    """
    paths = dict(_VIEWS)
    views = "".join(
        f'<a class="tab{" on" if name == view else ""}" '
        f'href="{path}?{"platform=" + escape(platform) + "&" if platform else ""}'
        f'key={escape(key)}">{name}</a>'
        for name, path in _VIEWS
    )
    target = paths[view] if platform is not None else paths["Capture"]
    platforms = "".join(
        f'<a class="tab{" on" if name == platform else ""}" '
        f'href="{target}?platform={name}&key={escape(key)}">{escape(name)}</a>'
        for name in sorted(PLATFORM_TABLES)
    )
    return (
        f'<div class="tabs">{views}'
        '<span class="tabgap"></span>'
        f"{platforms}</div>"
    )


#: Shared by every page, so they cannot drift apart visually.
_SHARED_CSS = """  :root {
    color-scheme: light;
    --surface: #fcfcfb; --panel: #ffffff; --line: #e5e4e0;
    --ink: #0b0b0b; --ink-2: #52514e; --ink-3: #82817c;
    --good: #0ca30c; --warn: #fab219; --crit: #d03b3b; --accent: #2a78d6;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --surface: #1a1a19; --panel: #232322; --line: #34332f;
      --ink: #ffffff; --ink-2: #c3c2b7; --ink-3: #8f8e85;
      --accent: #3987e5;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding-block: 24px; padding-inline: 16px;
    background: var(--surface); color: var(--ink);
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  }
  .wrap { max-width: 1180px; margin: 0 auto; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: var(--ink-2); margin: 0 0 20px; }
  .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
  .tab {
    padding: 6px 14px; border: 1px solid var(--line); border-radius: 999px;
    color: var(--ink-2); text-decoration: none; background: var(--panel);
  }
  .tab.on { border-color: var(--accent); color: var(--accent); font-weight: 600; }
  .tiles {
    display: grid; gap: 12px; margin-bottom: 28px;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  }
  .tile {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; padding: 14px 16px;
  }
  .tile .label { color: var(--ink-2); font-size: 12px; }
  .tile .value { font-size: 28px; font-weight: 600; margin-top: 2px; }
  .tile .note { color: var(--ink-3); font-size: 12px; margin-top: 2px; }
  h2 { font-size: 15px; margin: 0 0 10px; }
  .panel {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; overflow-x: auto; margin-bottom: 28px;
  }
  /* min-width keeps the table scrolling sideways on a phone instead of
     squeezing every column down to one word per line. */
  table { width: 100%; min-width: 900px; border-collapse: collapse; font-size: 13px; }
  table.narrow { min-width: 620px; }
  th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--line); }
  th { color: var(--ink-2); font-weight: 600; white-space: nowrap; }
  tr:last-child td { border-bottom: 0; }
  td.when { white-space: nowrap; color: var(--ink-2); }
  td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
  td.caption { min-width: 260px; max-width: 340px; color: var(--ink-2); }
  .muted { color: var(--ink-3); }
  .empty { padding: 28px 12px; text-align: center; color: var(--ink-3); }
  a { color: var(--accent); }
  .flag { font-size: 12px; white-space: nowrap; margin-right: 6px; }
  .flag.good { color: var(--good); }
  .flag.warn { color: var(--warn); }
  .flag.crit { color: var(--crit); }
  .flag.approx, .flag.ad, .flag.ai, .flag.muted { color: var(--ink-3); }
  .prov { font-size: 11px; color: var(--ink-3); }
  .prov.exact { color: var(--good); }
  td.vid { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .todo {
    background: var(--panel); border: 1px solid var(--warn);
    border-radius: 10px; padding: 14px 16px; margin: 0 0 24px;
    color: var(--ink-2);
  }
  .todo code {
    display: block; margin-top: 8px; padding: 9px 11px;
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 7px; color: var(--ink);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px; word-break: break-all;
  }
  footer { color: var(--ink-3); font-size: 12px; }
  .warn-text { color: var(--warn); }
  .caveats {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; padding: 16px 20px; margin-bottom: 24px;
  }
  .caveats ul { margin: 0; padding-left: 20px; color: var(--ink-2); }
  .caveats li { margin-bottom: 8px; }
  .caveats li:last-child { margin-bottom: 0; }
  /* Review chips: one exclusion category each, with its count. */
  .chips { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 14px; }
  .chip {
    padding: 4px 11px; border: 1px solid var(--line); border-radius: 999px;
    background: var(--panel); color: var(--ink-2); text-decoration: none;
    font-size: 12px; white-space: nowrap;
  }
  .chip.on { border-color: var(--accent); color: var(--accent); font-weight: 600; }
  /* New videos per day. One series, so the heading names it and the
     counts are labelled directly rather than read off an axis. */
  .days { margin-bottom: 26px; max-width: 520px; }
  .day { display: flex; align-items: center; gap: 10px; margin-bottom: 5px; }
  .dlabel {
    width: 48px; font-size: 12px; color: var(--ink-2);
    font-variant-numeric: tabular-nums; flex: none;
  }
  .dtrack { flex: 1; height: 14px; }
  .dbar {
    display: block; height: 14px; border-radius: 4px;
    background: var(--accent); min-width: 2px;
  }
  .dcount {
    width: 34px; font-size: 12px; color: var(--ink-2);
    font-variant-numeric: tabular-nums; flex: none;
  }
  td.rank { color: var(--ink-3); font-variant-numeric: tabular-nums; width: 38px; }
  .empty code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
  }
"""


def _page(**ctx) -> str:
    platform = ctx["platform"]
    tabs = _nav("Capture", platform, ctx["key"])

    tiles = "".join(
        [
            _tile("In the corpus", _compact(ctx["unique"]), "unique videos, on topic"),
            _tile("New in 24 hours", _compact(ctx["day"]), "first seen"),
            _tile("New in 3 days", _compact(ctx["three"]), "first seen"),
            _tile(
                "With a video ID",
                _pct(ctx["with_id"], ctx["posts"]),
                f"{ctx['with_id']:,} of {ctx['posts']:,} collected",
            ),
            _tile(
                "Publication time known",
                _pct(ctx["dated"], len(ctx["rows"])),
                "of the rows below",
            ),
            _tile(
                "Links to resolve",
                _compact(ctx["unresolved"]),
                "copied, not yet followed",
            ),
            _tile(
                "Off topic",
                _compact(ctx["filtered"]),
                "hidden, not deleted",
            ),
        ]
    )

    # One series, so no legend: the heading names it. Counts are
    # labelled directly rather than read off an axis.
    peak = max((count for _, count in ctx["per_day"]), default=0)
    bars = "".join(
        f'<div class="day">'
        f'<span class="dlabel">{escape(date[5:])}</span>'
        f'<span class="dtrack"><span class="dbar" '
        f'style="width:{round(100 * count / peak) if peak else 0}%" '
        f'title="{count} new on {escape(date)}"></span></span>'
        f'<span class="dcount">{count}</span>'
        "</div>"
        for date, count in ctx["per_day"]
    )

    # Resolving is a deliberate step -- it makes outbound requests from
    # wherever the researcher runs it -- so the page asks for it by
    # name instead of quietly doing it.
    todo = (
        f'<p class="todo"><strong>{ctx["unresolved"]:,} copied link(s)</strong> still '
        "need following to their real video ID. On the machine running this server:"
        "<code>cd backend &amp;&amp; ./.venv/bin/python -m app.resolve</code>"
        "Then reload this page.</p>"
        if ctx["unresolved"]
        else ""
    )

    # A filter that cannot be inspected is a filter that has to be
    # trusted, which is not good enough for deciding what is in a
    # corpus. So every category is one click away, with its count.
    def review(label: str, value: str, count: int | None = None) -> str:
        on = " on" if ctx["show"] == value else ""
        suffix = f" {count:,}" if count is not None else ""
        query = f"platform={escape(platform)}"
        if value:
            query += f"&show={escape(value)}"
        return (
            f'<a class="chip{on}" href="/dashboard?{query}'
            f'&key={escape(ctx["key"])}">{escape(label)}{suffix}</a>'
        )

    policy = filter_policy(platform)
    if policy != "none":
        chips = [
            review("in scope", ""),
            # The corpus splits in two, and the split is the point:
            # scripted drama is in scope and is tracked, but it has no
            # author to interview and a channel posting episodes on a
            # schedule is not the population this study is about.
            review("firsthand", "firsthand", ctx["firsthand"]),
            review("scripted drama", "fiction only", ctx["fiction"]),
            review("everything", "all"),
            review("excluded", "excluded", ctx["filtered"]),
        ]
        chips += [
            review(reason, reason, count)
            for reason, count in sorted(ctx["reasons"].items(), key=lambda p: -p[1])
        ]
        if policy == "full":
            said = "Review what the topic filter did."
        elif policy == "search":
            said = (
                "The search term is the filter on this platform. "
                "<code>Chinese lesbian</code> and 中国女同 name the population "
                "directly, and what they surface is largely diaspora creators "
                "captioning in English &mdash; so no row is excluded here for "
                "being in English or for lacking a topic term. Keyword "
                "collisions still are."
            )
        else:
            said = (
                "Language filter only on this platform &mdash; the search chose "
                "the topic, so no row is excluded for lacking a topic term."
            )
        filter_note = (
            f'<p class="note-line">{said} Excluded rows are '
            "hidden, never deleted &mdash; read a category before trusting it.</p>"
            f'<div class="chips">{"".join(chips)}</div>'
        )
    else:
        # Saying "no filter here" out loud matters more than the chips
        # did. A page that shows everything on one platform and a
        # filtered subset on another invites reading the two counts as
        # comparable, which they are not.
        filter_note = (
            '<p class="note-line">No topic filter on this platform. It is sampled '
            "from community hashtags (#lwl, #wlw, #les) that the community applies "
            "to its own posts, so the search is the filter and every row collected "
            "is in the corpus. YouTube is topic-filtered and TikTok is sampled "
            "on a different search term entirely, so counts across the three "
            "are not comparable.</p>"
        )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Capture dashboard</title>
<style>{_SHARED_CSS}</style>
</head><body><div class="wrap">

<h1>Capture dashboard</h1>
<p class="sub">Read-only. Engagement counts are read from the rendered app UI and
are approximate wherever flagged. Times are {escape(settings.display_timezone)};
stored in UTC.</p>

<div class="tabs">{tabs}</div>
<div class="tiles">{tiles}</div>

{todo}

<h2>New videos per day &mdash; {escape(platform)}</h2>
<p class="note-line">Unique videos in the corpus, counted on the day each was
first collected. A video already held is not new data.</p>
<div class="days">{bars}</div>

<h2>Videos &mdash; {escape(platform)}</h2>
{filter_note}
<div class="panel"><table>
<thead><tr>
<th>#</th><th>Published</th><th>Video ID</th><th>@handle</th><th>Display name</th>
<th>Caption</th><th>Seen</th>
<th class="n">Likes</th><th class="n">Comments</th><th class="n">Shares</th>
<th>Notes</th><th>Seen on</th>
</tr></thead>
<tbody>{_video_rows(ctx["rows"])}</tbody>
</table></div>

<footer>
Showing the most recent {_ROW_LIMIT} rows.
Download the corpus as
<a href="/api/export/posts.csv?platform={escape(platform)}&key={escape(ctx["key"])}">CSV</a>,
or <a href="/api/export/posts.csv?platform={escape(platform)}&show=all&key={escape(ctx["key"])}">everything
collected</a>.
</footer>
</div></body></html>"""


@router.get("/", response_class=HTMLResponse)
def install_page(request: Request) -> HTMLResponse:
    """Setup page for the phone.

    Opening the backend's own address is the natural first thing to try
    on a phone, so that address serves what is needed there: the APK
    download and the server address to type into the app. The address
    is read back off the request, so it is always exactly right rather
    than something to copy across from a terminal.

    No authentication: it exposes no collected data, only the address
    of the host the request already reached.
    """
    host = request.headers.get("host", "").strip()
    server_url = f"http://{host}" if host else ""

    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Set up the capture app</title>
<style>
  :root {{
    color-scheme: light;
    --surface: #fcfcfb; --panel: #ffffff; --line: #e5e4e0;
    --ink: #0b0b0b; --ink-2: #52514e; --ink-3: #82817c;
    --accent: #2a78d6; --good: #0ca30c;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      color-scheme: dark;
      --surface: #1a1a19; --panel: #232322; --line: #34332f;
      --ink: #ffffff; --ink-2: #c3c2b7; --ink-3: #8f8e85;
      --accent: #3987e5;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding-block: 28px; padding-inline: 16px;
    background: var(--surface); color: var(--ink);
    font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  }}
  .wrap {{ max-width: 520px; margin: 0 auto; }}
  h1 {{ font-size: 21px; margin: 0 0 6px; }}
  .sub {{ color: var(--ink-2); margin: 0 0 26px; }}
  .step {{
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 12px; padding: 16px 18px; margin-bottom: 14px;
  }}
  .n {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; border-radius: 999px;
    background: var(--accent); color: #fff;
    font-size: 13px; font-weight: 600; margin-right: 8px;
  }}
  h2 {{ font-size: 16px; margin: 0 0 8px; display: flex; align-items: center; }}
  p {{ margin: 0 0 10px; color: var(--ink-2); }}
  p:last-child {{ margin-bottom: 0; }}
  .cta {{
    display: block; text-align: center; text-decoration: none;
    background: var(--accent); color: #fff; font-weight: 600;
    padding: 14px; border-radius: 10px; margin: 4px 0 2px;
  }}
  code {{
    display: block; background: var(--surface); border: 1px solid var(--line);
    border-radius: 8px; padding: 11px 13px; margin: 8px 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 15px; word-break: break-all; color: var(--ink);
  }}
  .ok {{ color: var(--good); font-weight: 600; }}
  footer {{ color: var(--ink-3); font-size: 13px; margin-top: 22px; }}
  a {{ color: var(--accent); }}
</style>
</head><body><div class="wrap">

<h1>Set up the capture app</h1>
<p class="sub">You reached the backend, so the phone and this server can talk.
<span class="ok">&check;</span></p>

<div class="step">
  <h2><span class="n">1</span>Install the app</h2>
  <p>Android will ask whether to allow installing from your browser. Allow it.</p>
  <a class="cta" href="{escape(settings.apk_download_url)}">Download the APK</a>
  <p style="margin-top:10px">Already installed? Re-downloading from here replaces it
  with the current build.</p>
</div>

<div class="step">
  <h2><span class="n">2</span>Register</h2>
  <p>Open <strong>Video Capture</strong> &rarr; <strong>Register device</strong>.
  Enter your enrolled email, and this as the server:</p>
  <code>{escape(server_url)}</code>
</div>

<div class="step">
  <h2><span class="n">3</span>Turn on capture</h2>
  <p>Tap <strong>Enable capture service</strong>, find
  <strong>Video Capture</strong> under <em>Downloaded apps</em>, and switch it on.</p>
  <p>It reads Douyin and TikTok only &mdash; the restriction is enforced by
  Android, not just by the app.</p>
</div>

<div class="step">
  <h2><span class="n">4</span>Scroll, then check</h2>
  <p>Scroll a few videos slowly, a few seconds each. A post is recorded once it
  has been off screen for 5&nbsp;seconds.</p>
  <p>Open the dashboard on your laptop to watch rows arrive.</p>
</div>

<footer>
Research tooling. Comment text and video files are never collected.
<a href="/healthz">Server status</a>
</footer>
</div></body></html>"""
    )


# --------------------------------------------------------------------
# Takedown findings
# --------------------------------------------------------------------

_VERDICT_CLASS = {
    ALIVE: "good",
    GONE: "crit",
    AUTHOR_GONE: "crit",
    WITHHELD: "warn",
}


def _duration(span) -> str:
    """Days and hours. Minutes would imply precision we do not have."""
    if span is None:
        return "—"
    hours = int(span.total_seconds() // 3600)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    return f"{hours}h" if hours else "<1h"


def _lifetime_cell(finding: Finding) -> str:
    """The removal window, as a bracket.

    A single number here would present the checking schedule as a
    property of the platform. See app/survival.py.
    """
    bounds = finding.lifetime()
    if bounds is None:
        return '<td class="muted">&mdash;</td>'
    lower, upper = bounds
    if _duration(lower) == _duration(upper):
        return f'<td class="when">{escape(_duration(upper))}</td>'
    return (
        f'<td class="when">{escape(_duration(lower))}&ndash;{escape(_duration(upper))}'
        f'<div class="prov">window {escape(_duration(finding.uncertainty))}</div></td>'
    )


def _finding_rows(items: list[Finding]) -> str:
    if not items:
        return (
            '<tr><td colspan="9" class="empty">No links have been re-checked yet. '
            "Run <code>python -m app.recheck</code>.</td></tr>"
        )

    out = []
    for finding in items:
        verdict = finding.outcome or finding.current
        state = (
            f'<span class="flag {_VERDICT_CLASS.get(verdict, "muted")}">'
            f'{escape(verdict or "not measured")}</span>'
        )
        published = finding.published_at
        link = (
            f'<a href="{escape(finding.url)}" rel="noreferrer noopener" '
            f'target="_blank">{escape(finding.video_id)}</a>'
            if finding.url
            else escape(finding.video_id)
        )
        doubtful = (
            '<div class="prov warn-text">mostly uninformative</div>'
            if finding.checks and finding.uninformative * 2 > finding.checks
            else ""
        )
        out.append(
            "<tr>"
            f'<td>{state}{doubtful}</td>'
            f'<td class="vid">{link}</td>'
            f"{_cell(finding.author_handle)}"
            f'<td class="when">{escape(local(published).strftime("%Y-%m-%d %H:%M")) if published else "—"}</td>'
            f"{_lifetime_cell(finding)}"
            f'<td class="when">{escape(local(finding.last_alive_at).strftime("%m-%d %H:%M")) if finding.last_alive_at else "—"}</td>'
            f'<td class="when">{escape(local(finding.first_gone_at).strftime("%m-%d %H:%M")) if finding.first_gone_at else "—"}</td>'
            f'<td class="when">{escape(local(finding.last_checked_at).strftime("%m-%d %H:%M")) if finding.last_checked_at else "—"}</td>'
            f'<td class="n">{finding.checks}</td>'
            "</tr>"
        )
    return "".join(out)


@router.get("/dashboard/takedowns", response_class=HTMLResponse)
def takedowns(
    key: str = Depends(require_admin_view),
    platform: str = Query(default="tiktok"),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if platform not in PLATFORM_TABLES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown platform {platform}"
        )

    items = findings(session, platform)
    summary = summarise(items)
    collected = [t for t in collected_targets(session) if t.platform == platform]
    due = due_targets(session, targets=collected)

    # The corpus is two populations and they are not pooled. See
    # app/relevance.py: a 百合短剧 channel posting episodes on a
    # schedule and a person posting their own life do not face the
    # same moderation, and one rate over both describes neither.
    scripted = fiction_ids(session, platform)
    fiction = summarise([item for item in items if item.video_id in scripted])
    firsthand = summarise([item for item in items if item.video_id not in scripted])

    return HTMLResponse(
        _findings_page(
            key=key,
            platform=platform,
            items=items,
            summary=summary,
            fiction=fiction,
            firsthand=firsthand,
            # Whether the corpus holds any scripted drama at all, which
            # is what decides the split -- not whether any of it has
            # been checked yet.
            has_fiction=bool(scripted),
            collected=len(collected),
            due=len(due),
        )
    )


def _rate_tile(label: str, summary) -> str:
    """A takedown rate with the denominator it was computed over."""
    rate = summary.rate
    return _tile(
        label,
        "—" if rate is None else f"{round(100 * rate)}%",
        f"{summary.gone:,} of {summary.gone + summary.alive:,} measured",
    )


def _findings_page(**ctx) -> str:
    platform = ctx["platform"]
    summary = ctx["summary"]

    tabs = _nav("Takedowns", platform, ctx["key"])

    tiles = "".join(
        [
            _tile(
                "Videos tracked",
                _compact(summary.tracked),
                f"of {ctx['collected']:,} in the corpus with an ID",
            ),
            _tile("Disappeared", _compact(summary.gone), "at the latest check"),
            _rate_tile("Takedown rate", summary)
            if not ctx["has_fiction"]
            # Two populations, never pooled: see app/relevance.py.
            else _rate_tile("Rate — firsthand", ctx["firsthand"])
            + _rate_tile("Rate — scripted drama", ctx["fiction"]),
            _tile(
                "Not measured",
                _compact(summary.unmeasured + summary.doubtful),
                "excluded from the rate",
            ),
            _tile(
                "Timing precision",
                _duration(summary.median_uncertainty),
                "median removal window",
            ),
            _tile("Due for a check", _compact(ctx["due"]), "at the current cadence"),
        ]
    )

    todo = (
        f'<p class="todo"><strong>{ctx["due"]:,} link(s)</strong> are due for a check.'
        "<code>cd backend &amp;&amp; ./.venv/bin/python -m app.recheck</code>"
        "Run it once a day; the schedule thins out as a video ages.</p>"
        if ctx["due"]
        else ""
    )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Takedown findings</title>
<style>{_SHARED_CSS}</style>
</head><body><div class="wrap">

<h1>Takedown findings</h1>
<p class="sub">How long each collected video survived. Removal times are
<strong>intervals</strong>: a video seen alive on one check and gone on the next
disappeared somewhere between them, and nothing in the data says where.</p>

<div class="tabs">{tabs}</div>
<div class="tiles">{tiles}</div>
{todo}

<h2>Per video &mdash; {escape(platform)}</h2>
<div class="panel"><table>
<thead><tr>
<th>Outcome</th><th>Video ID</th><th>@handle</th><th>Published</th>
<th>Lifetime</th><th>Last alive</th><th>First gone</th><th>Last checked</th>
<th class="n">Checks</th>
</tr></thead>
<tbody>{_finding_rows(ctx["items"])}</tbody>
</table></div>

<div class="caveats">
<h2>Read these before quoting a rate</h2>
<ul>
<li><strong>One vantage point.</strong> These checks run from wherever the
command was run. A video restricted in one country and visible in another is
indistinguishable from an available one. Regional blocking is not measured.</li>
<li><strong>Who removed it is not in the response.</strong> An author deleting
a post and a platform pulling it can return the same page. <em>gone</em> means
unwatchable, not <em>moderated</em>. Interviews, not this table, separate
those.</li>
<li><strong>Not measured is not alive.</strong> Failed requests, bot
challenges and unrecognised pages are excluded from the rate, never counted as
survivals. A large count there means the rate is not yet trustworthy.</li>
<li><strong>The marker list is checkable, not verified.</strong> Classification
reads the platform's own wording. Confirm it against one genuinely removed
video before trusting these numbers; the raw response is stored, so a corrected
list can be re-applied to every check already made.</li>
<li><strong>Only videos with an ID are here.</strong> A captured post with no
copied link cannot be re-checked at all, so this table is a subset of what was
observed &mdash; report which fraction.</li>
</ul>
</div>

<footer>Findings are computed from the stored checks, never from a saved
verdict &mdash; correcting the classification re-reads the whole history.</footer>
</div></body></html>"""


# --------------------------------------------------------------------
# Overview: all three platforms at once
# --------------------------------------------------------------------

#: State colours are the reserved status steps, and red-vs-green is the
#: one pair colour-blind readers cannot separate. So every segment also
#: carries a glyph, a direct count and a row in the table below --
#: colour never carries the meaning on its own.
_STATES = (
    ("alive", "still up", "good", "●"),
    ("gone", "disappeared", "crit", "✕"),
    ("unmeasured", "not measured", "mute", "○"),
)


@dataclass
class PlatformRow:
    """One platform's totals, for the overview."""

    platform: str
    captured: int = 0
    with_id: int = 0
    alive: int = 0
    gone: int = 0
    unmeasured: int = 0

    @property
    def tracked(self) -> int:
        return self.alive + self.gone + self.unmeasured

    @property
    def measured(self) -> int:
        return self.alive + self.gone

    @property
    def rate(self) -> float | None:
        return None if not self.measured else self.gone / self.measured


def _platform_rows(session: Session) -> list[PlatformRow]:
    rows = []
    for platform in sorted(PLATFORM_TABLES):
        model, _ = PLATFORM_TABLES[platform]
        row = PlatformRow(platform=platform)
        row.captured = session.scalar(select(func.count()).select_from(model)) or 0
        row.with_id = (
            session.scalar(
                select(func.count()).select_from(model).where(model.video_id.isnot(None))
            )
            or 0
        )
        summary = summarise(findings(session, platform))
        row.alive, row.gone = summary.alive, summary.gone
        row.unmeasured = summary.unmeasured + summary.doubtful
        rows.append(row)
    return rows


def _bar(row: PlatformRow) -> str:
    """A stacked bar of one platform's check outcomes.

    Flex rather than SVG so it reflows with the page, with a 2px gap
    between segments so adjacent fills never touch. The title
    attributes give a hover readout without any JavaScript.
    """
    if not row.tracked:
        return '<div class="bar empty-bar" title="nothing re-checked yet"></div>'

    segments = []
    for key, label, tone, glyph in _STATES:
        count = getattr(row, key)
        if not count:
            continue
        share = round(100 * count / row.tracked)
        # Below ~9% a number inside the segment collides with its edge.
        inner = f"{glyph} {count}" if share >= 9 else ""
        segments.append(
            f'<span class="seg {tone}" style="flex:{count}" '
            f'title="{escape(label)}: {count} of {row.tracked} ({share}%)">'
            f"{escape(inner)}</span>"
        )
    return f'<div class="bar">{"".join(segments)}</div>'


def _corpus_share(count: int, total: int) -> str:
    return "—" if not total else f"{round(100 * count / total)}%"


def _overview_rows(rows: list[PlatformRow], captured_total: int) -> str:
    out = []
    for row in rows:
        out.append(
            "<tr>"
            f"<td><strong>{escape(row.platform)}</strong></td>"
            f'<td class="n">{row.captured:,}</td>'
            f'<td class="n">{escape(_corpus_share(row.captured, captured_total))}</td>'
            f'<td class="n">{row.with_id:,}</td>'
            f'<td class="n">{row.alive:,}</td>'
            f'<td class="n">{row.gone:,}</td>'
            f'<td class="n">{row.unmeasured:,}</td>'
            f'<td class="n">{"—" if row.rate is None else f"{round(100 * row.rate)}%"}</td>'
            "</tr>"
        )
    return "".join(out)


@router.get("/dashboard/overview", response_class=HTMLResponse)
def overview(
    key: str = Depends(require_admin_view),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    rows = _platform_rows(session)
    return HTMLResponse(_overview_page(key=key, rows=rows))


def _overview_page(**ctx) -> str:
    rows: list[PlatformRow] = ctx["rows"]
    captured = sum(row.captured for row in rows)
    with_id = sum(row.with_id for row in rows)
    gone = sum(row.gone for row in rows)
    alive = sum(row.alive for row in rows)
    unmeasured = sum(row.unmeasured for row in rows)
    measured = gone + alive

    tiles = "".join(
        [
            _tile("Videos collected", _compact(captured), "all platforms"),
            _tile(
                "Re-checkable",
                _pct(with_id, captured),
                f"{with_id:,} have a video ID",
            ),
            _tile("Disappeared", _compact(gone), "at the latest check"),
            _tile("Still up", _compact(alive), "at the latest check"),
            _tile(
                "Takedown rate",
                "—" if not measured else f"{round(100 * gone / measured)}%",
                f"{gone:,} of {measured:,} measured",
            ),
            _tile("Not measured", _compact(unmeasured), "excluded from the rate"),
        ]
    )

    legend = "".join(
        f'<span class="key"><span class="dot {tone}"></span>{escape(glyph)} {escape(label)}</span>'
        for _, label, tone, glyph in _STATES
    )

    bars = "".join(
        f'<div class="barrow"><div class="barlabel">{escape(row.platform)}'
        f'<span class="muted"> {row.tracked:,} tracked</span></div>{_bar(row)}</div>'
        for row in rows
    )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Overview</title>
<style>{_SHARED_CSS}
  .barrow {{ margin-bottom: 14px; }}
  .barlabel {{ font-size: 13px; margin-bottom: 5px; }}
  .bar {{ display: flex; gap: 2px; height: 26px; }}
  .bar .seg {{
    display: flex; align-items: center; justify-content: center;
    font-size: 11px; color: #fff; overflow: hidden; white-space: nowrap;
  }}
  .bar .seg:first-child {{ border-radius: 4px 0 0 4px; }}
  .bar .seg:last-child {{ border-radius: 0 4px 4px 0; }}
  .bar .seg:only-child {{ border-radius: 4px; }}
  .seg.good {{ background: var(--good); }}
  .seg.crit {{ background: var(--crit); }}
  .seg.mute {{ background: var(--ink-3); }}
  .empty-bar {{
    background: var(--surface); border: 1px dashed var(--line); border-radius: 4px;
  }}
  .keys {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 18px; }}
  .key {{ font-size: 12px; color: var(--ink-2); }}
  .dot {{
    display: inline-block; width: 10px; height: 10px;
    border-radius: 2px; margin-right: 6px; vertical-align: -1px;
  }}
  .dot.good {{ background: var(--good); }}
  .dot.crit {{ background: var(--crit); }}
  .dot.mute {{ background: var(--ink-3); }}
</style>
</head><body><div class="wrap">

<h1>Overview</h1>
<p class="sub">Every platform, one page. Rates count only videos actually
measured; anything unreachable is left out rather than assumed still up.</p>

{_nav("Overview", None, ctx["key"])}
<div class="tiles">{tiles}</div>

<h2>Check outcomes by platform</h2>
<div class="keys">{legend}</div>
{bars}

<h2>The same numbers</h2>
<div class="panel"><table class="narrow">
<thead><tr>
<th>Platform</th><th class="n">Collected</th><th class="n">Share</th>
<th class="n">With ID</th><th class="n">Still up</th><th class="n">Gone</th>
<th class="n">Not measured</th><th class="n">Rate</th>
</tr></thead>
<tbody>{_overview_rows(rows, captured)}</tbody>
</table></div>

<footer>Only videos with an ID can be re-checked, so "tracked" is a subset of
"collected". YouTube is collected through its API, so every one of its videos
has an ID; Douyin and TikTok need a copied link.</footer>
</div></body></html>"""
