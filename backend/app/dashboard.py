"""A read-only web view of what has been collected.

Server-rendered HTML with no build step and no JavaScript: the point is
to be able to open it on a phone during a collection run and see
whether data is actually arriving.
"""
from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import is_admin_key
from .config import settings
from .db import get_session
from .models import CaptureEvent, SharedLink
from .parsers import PLATFORM_TABLES
from .snowflake import derivation_is_verified
from .views import (
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
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if platform not in PLATFORM_TABLES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown platform {platform}"
        )
    model, _ = PLATFORM_TABLES[platform]

    posts = session.scalar(select(func.count()).select_from(model)) or 0
    with_id = (
        session.scalar(
            select(func.count()).select_from(model).where(model.video_id.isnot(None))
        )
        or 0
    )
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

    rows = video_rows(session, platform, _ROW_LIMIT)
    dated = sum(1 for row in rows if row.posted_display)

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
    NEEDS_RESOLVING: "warn",
    LINKED_BY_TIME: "warn",
    LINK_ONLY: "crit",
    NO_LINK: "muted",
    ID_ON_SCREEN: "good",
}

_COLUMNS = 11


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
    elif row.posted_source == "screen":
        note = '<div class="prov">from screen</div>'
    elif row.posted_source == "as shown":
        note = '<div class="prov">as shown</div>'
    return f'<td class="when">{escape(row.posted_display)}{note}</td>'


def _id_cell(row: VideoRow) -> str:
    if not row.video_id:
        # An unresolved short link has no id yet, but it does open, and
        # a row with nothing clickable in it looks like a row with no
        # data in it.
        if row.video_url:
            return (
                f'<td><a href="{escape(row.video_url)}" rel="noreferrer noopener" '
                'target="_blank">short link</a></td>'
            )
        return '<td class="muted">&mdash;</td>'
    if row.video_url:
        return (
            f'<td class="vid"><a href="{escape(row.video_url)}" '
            f'rel="noreferrer noopener" target="_blank">{escape(row.video_id)}</a></td>'
        )
    return f'<td class="vid">{escape(row.video_id)}</td>'


def _notes_cell(row: VideoRow) -> str:
    notes = [
        f'<span class="flag {_STATE_CLASS.get(row.state, "good")}">'
        f"{escape(row.state)}</span>"
    ]
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
    for row in rows:
        out.append(
            "<tr>"
            f"{_posted_cell(row)}"
            f"{_id_cell(row)}"
            f"{_cell(row.author_handle)}"
            f"{_cell(row.author_name)}"
            f'<td class="caption">{escape((row.caption or "—")[:110])}</td>'
            f"<td class=\"when\">{escape(row.when.strftime('%m-%d %H:%M'))}</td>"
            f"{_cell(row.feed)}"
            f"{_num(row.like_count)}{_num(row.comment_count)}{_num(row.share_count)}"
            f"{_notes_cell(row)}"
            "</tr>"
        )
    return "".join(out)


def _page(**ctx) -> str:
    platform = ctx["platform"]
    tabs = "".join(
        f'<a class="tab{" on" if name == platform else ""}" '
        f'href="/dashboard?platform={name}&key={escape(ctx["key"])}">{escape(name)}</a>'
        for name in sorted(PLATFORM_TABLES)
    )

    tiles = "".join(
        [
            _tile("Videos captured", _compact(ctx["posts"]), platform),
            _tile(
                "With a video ID",
                _pct(ctx["with_id"], ctx["posts"]),
                f"{ctx['with_id']:,} of {ctx['posts']:,} &mdash; re-checkable",
                raw_note=True,
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
                "Counts approximate",
                _pct(ctx["approximate"], ctx["posts"]),
                "abbreviated in the UI",
            ),
            _tile("Observations stored", _compact(ctx["events"]), "all platforms"),
        ]
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

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Capture dashboard</title>
<style>
  :root {{
    color-scheme: light;
    --surface: #fcfcfb; --panel: #ffffff; --line: #e5e4e0;
    --ink: #0b0b0b; --ink-2: #52514e; --ink-3: #82817c;
    --good: #0ca30c; --warn: #fab219; --crit: #d03b3b; --accent: #2a78d6;
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
    margin: 0; padding-block: 24px; padding-inline: 16px;
    background: var(--surface); color: var(--ink);
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  }}
  .wrap {{ max-width: 1180px; margin: 0 auto; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .sub {{ color: var(--ink-2); margin: 0 0 20px; }}
  .tabs {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }}
  .tab {{
    padding: 6px 14px; border: 1px solid var(--line); border-radius: 999px;
    color: var(--ink-2); text-decoration: none; background: var(--panel);
  }}
  .tab.on {{ border-color: var(--accent); color: var(--accent); font-weight: 600; }}
  .tiles {{
    display: grid; gap: 12px; margin-bottom: 28px;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  }}
  .tile {{
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; padding: 14px 16px;
  }}
  .tile .label {{ color: var(--ink-2); font-size: 12px; }}
  .tile .value {{ font-size: 28px; font-weight: 600; margin-top: 2px; }}
  .tile .note {{ color: var(--ink-3); font-size: 12px; margin-top: 2px; }}
  h2 {{ font-size: 15px; margin: 0 0 10px; }}
  .panel {{
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; overflow-x: auto; margin-bottom: 28px;
  }}
  /* min-width keeps the table scrolling sideways on a phone instead of
     squeezing every column down to one word per line. */
  table {{ width: 100%; min-width: 900px; border-collapse: collapse; font-size: 13px; }}
  table.narrow {{ min-width: 620px; }}
  th, td {{ padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--line); }}
  th {{ color: var(--ink-2); font-weight: 600; white-space: nowrap; }}
  tr:last-child td {{ border-bottom: 0; }}
  td.when {{ white-space: nowrap; color: var(--ink-2); }}
  td.n, th.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.caption {{ min-width: 260px; max-width: 340px; color: var(--ink-2); }}
  .muted {{ color: var(--ink-3); }}
  .empty {{ padding: 28px 12px; text-align: center; color: var(--ink-3); }}
  a {{ color: var(--accent); }}
  .flag {{ font-size: 12px; white-space: nowrap; margin-right: 6px; }}
  .flag.good {{ color: var(--good); }}
  .flag.warn {{ color: var(--warn); }}
  .flag.crit {{ color: var(--crit); }}
  .flag.approx, .flag.ad, .flag.ai, .flag.muted {{ color: var(--ink-3); }}
  .prov {{ font-size: 11px; color: var(--ink-3); }}
  .prov.exact {{ color: var(--good); }}
  td.vid {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .todo {{
    background: var(--panel); border: 1px solid var(--warn);
    border-radius: 10px; padding: 14px 16px; margin: 0 0 24px;
    color: var(--ink-2);
  }}
  .todo code {{
    display: block; margin-top: 8px; padding: 9px 11px;
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 7px; color: var(--ink);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px; word-break: break-all;
  }}
  footer {{ color: var(--ink-3); font-size: 12px; }}
</style>
</head><body><div class="wrap">

<h1>Capture dashboard</h1>
<p class="sub">Read-only. Engagement counts are read from the rendered app UI and
are approximate wherever flagged.</p>

<div class="tabs">{tabs}</div>
<div class="tiles">{tiles}</div>

{todo}

<h2>Videos &mdash; {escape(platform)}</h2>
<div class="panel"><table>
<thead><tr>
<th>Published</th><th>Video ID</th><th>@handle</th><th>Display name</th>
<th>Caption</th><th>Seen</th><th>Feed</th>
<th class="n">Likes</th><th class="n">Comments</th><th class="n">Shares</th>
<th>Notes</th>
</tr></thead>
<tbody>{_video_rows(ctx["rows"])}</tbody>
</table></div>

<footer>
Showing the most recent {_ROW_LIMIT} rows.
Full data: <a href="/api/export/posts.csv?platform={escape(platform)}&key={escape(ctx["key"])}">download CSV</a>.
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
