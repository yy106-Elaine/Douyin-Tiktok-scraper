"""A standalone page of charts, written out as one self-contained file.

    ./.venv/bin/python -m app.report --out takedowns.html

`app.analyse` prints the numbers; this draws them. It is a separate
artefact from the dashboard on purpose:

 -- The dashboard is an *operations* view. It is live, it needs the
    server running, it is keyed to an admin key, and it shows every
    row including the ones still being resolved. It answers "is
    collection working right now".

 -- This is an *analysis* view. It is a dated snapshot of aggregates,
    it is one file with nothing fetched from the network, and it opens
    from a USB stick on a machine that has never seen this repository.
    It answers "what does the collection say so far".

The second property is the reason it is a file and not a route. A
finding has to be quotable: a page that silently changes its numbers
between the day it was read and the day it is cited is not evidence of
anything. Every run writes the collection date into the page, and two
runs on different days are two documents.

Aggregates only, by default. No captions, no handles, and video ids
are shown as their last four digits unless `--identifiers` is passed.
These are posts by identifiable people on a sensitive topic, a page
that can be mailed around is a page that can leak, and nothing on it
needs the full id to be read. The per-video detail stays where it is
already protected: the admin dashboard and the local CSV.

There is a little JavaScript, for the hover readouts -- the one place
this file departs from the dashboard's no-script rule. Every value it
can show is also in the table under each chart, so the page is
complete with scripting off.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape

from sqlalchemy.orm import Session

from .analyse import HORIZONS, PLATFORMS, daily_hazard, own
from .clock import local, now as clock_now, today as clock_today
from .survival import Finding, by_collection_age, horizon, summarise

#: Sequential blue, low magnitude to high. Light goes light->dark;
#: dark goes dark->light, because on a dark surface the lighter step
#: is the louder one and "more" has to be the louder one. Both runs
#: pass the ordinal checks (monotone lightness, >= 0.06 steps between
#: them, the end nearest the surface clearing 2:1) -- see the data-viz
#: validator, not an eyeball.
RAMP_LIGHT = ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b")
RAMP_DARK = ("#184f95", "#256abf", "#3987e5", "#86b6ef", "#cde2fb")

#: Only ever one series on this page, so one hue does all the work and
#: no categorical palette is needed. Where a chart would have wanted
#: several series it is faceted into small multiples instead.
SERIES = "var(--series-1)"

PRETTY = {
    "douyin": "Douyin video",
    "douyin_note": "Douyin 图文",
    "tiktok": "TikTok",
    "youtube": "YouTube",
}


def label_for(platform: str) -> str:
    return PRETTY.get(platform, platform)


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def _pct1(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _span(span: timedelta | None) -> str:
    if span is None:
        return "—"
    hours = span.total_seconds() / 3600
    return f"{hours / 24:.1f}d" if hours >= 24 else f"{hours:.0f}h"


def _when(moment: datetime | None) -> str:
    shown = local(moment)
    return "—" if shown is None else shown.strftime("%Y-%m-%d %H:%M")


def mask(video_id: str, reveal: bool) -> str:
    """The last six digits, unless the caller asked for the whole id.

    A reader of this page needs to tell two rows apart; six digits do
    that without carrying enough of the id to find the post again. The
    whole id is a `--identifiers` run away for the researcher, who has
    the database anyway.
    """
    if reveal:
        return video_id
    return f"…{video_id[-6:]}" if len(video_id) > 6 else video_id


# -- marks ------------------------------------------------------------


@dataclass
class Bar:
    """One horizontal bar: a label, a share, and what to say on hover."""

    label: str
    value: float | None
    #: Printed at the tip. Kept separate from `value` so a bar can say
    #: "3/41" while being drawn as 7%.
    tip_text: str
    hover: str
    #: Shown in muted ink after the label -- the denominator, usually.
    note: str = ""


def hbars(bars: list[Bar], *, ident: str, width: int = 820) -> str:
    """Horizontal bars against a 0-100% scale.

    Horizontal because the categories are platform names, and a
    column chart would either clip "Douyin 图文" or turn it on its
    side. One hue: these are nominal categories and the bar length
    already carries the magnitude, so colouring them by size would
    spend the only free channel on information twice.
    """
    pad_left, pad_right, pad_top = 118, 44, 10
    row, thickness = 30, 14
    plot = width - pad_left - pad_right
    height = pad_top + row * len(bars) + 24

    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
           f'style="max-width:{width}px" aria-labelledby="{ident}-t">']
    out.append(f'<title id="{ident}-t">Share removed, by platform</title>')

    for tick in (0, 25, 50, 75, 100):
        x = pad_left + plot * tick / 100
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{pad_top}" '
                   f'x2="{x:.1f}" y2="{pad_top + row * len(bars)}" />')
        out.append(f'<text class="tick" x="{x:.1f}" '
                   f'y="{pad_top + row * len(bars) + 16}" '
                   f'text-anchor="middle">{tick}%</text>')
    out.append(f'<line class="axis" x1="{pad_left}" y1="{pad_top}" '
               f'x2="{pad_left}" y2="{pad_top + row * len(bars)}" />')

    for index, bar in enumerate(bars):
        mid = pad_top + row * index + row / 2
        out.append(f'<text class="cat" x="{pad_left - 10}" y="{mid + 4}" '
                   f'text-anchor="end">{_e(bar.label)}</text>')
        if bar.value is None:
            out.append(f'<text class="empty" x="{pad_left + 6}" y="{mid + 4}">'
                       f'{_e(bar.note or "not measured")}</text>')
            continue
        top = mid - thickness / 2
        if not bar.value:
            # A true zero is a tick on the baseline, not a sliver of
            # bar: a 2px stub reads as "a little bit" from across a
            # room, and the number beside it says none.
            out.append(f'<g class="mark" tabindex="0" data-tip="{_e(bar.hover)}">'
                       f'<rect class="hit" x="{pad_left}" y="{top - 8:.1f}" '
                       f'width="{plot}" height="{thickness + 16}" />'
                       f'<line class="zero" x1="{pad_left}" y1="{top:.1f}" '
                       f'x2="{pad_left}" y2="{top + thickness:.1f}" /></g>')
            out.append(f'<text class="value" x="{pad_left + 8}" '
                       f'y="{mid + 4}">{_e(bar.tip_text)}</text>')
            if bar.note:
                out.append(f'<text class="note-tick" x="{pad_left - 10}" '
                           f'y="{mid + 15}" text-anchor="end">'
                           f'{_e(bar.note)}</text>')
            continue
        length = max(plot * bar.value, 3.0)
        # Square at the baseline, 4px rounded at the data end: the
        # path is drawn by hand because a <rect> rounds both ends.
        radius = min(4.0, length)
        out.append(
            f'<g class="mark" tabindex="0" data-tip="{_e(bar.hover)}">'
            f'<rect class="hit" x="{pad_left}" y="{top - 8:.1f}" '
            f'width="{plot}" height="{thickness + 16}" />'
            f'<path class="bar" d="M{pad_left} {top:.1f} '
            f'h{length - radius:.1f} a{radius} {radius} 0 0 1 {radius} {radius} '
            f'v{thickness - 2 * radius} '
            f'a{radius} {radius} 0 0 1 -{radius} {radius} '
            f'H{pad_left} z" /></g>'
        )
        out.append(f'<text class="value" x="{pad_left + length + 8:.1f}" '
                   f'y="{mid + 4}">{_e(bar.tip_text)}</text>')
        if bar.note:
            out.append(f'<text class="note-tick" x="{pad_left - 10}" '
                       f'y="{mid + 15}" text-anchor="end">{_e(bar.note)}</text>')
    out.append("</svg>")
    return "".join(out)


@dataclass
class Column:
    """One column of a day series. `gap` draws a break, not a zero."""

    label: str
    value: int = 0
    at_risk: int = 0
    rate: float | None = None
    gap: bool = False


def columns(series: list[Column], *, ident: str, title: str,
            width: int = 820) -> str:
    """Counts per observed day, with the unobserved days drawn as breaks.

    The break is the point of the chart. A day the study did not run
    has no column and no zero; it has a `//` where the axis would have
    continued, so the reader can see that the series is not a calendar.
    """
    pad_left, pad_right, pad_top, pad_bottom = 34, 10, 14, 30
    plot_h = 96
    slots = len(series)
    width = max(width, pad_left + pad_right + slots * 26)
    slot = (width - pad_left - pad_right) / max(slots, 1)
    thickness = min(22.0, slot - 6)
    peak = max([c.value for c in series] or [0])
    scale = plot_h / peak if peak else 0
    height = pad_top + plot_h + pad_bottom

    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
           f'style="max-width:{width}px" aria-labelledby="{ident}-t">']
    out.append(f'<title id="{ident}-t">{_e(title)}</title>')

    for step in range(0, peak + 1, max(1, peak // 2 or 1)):
        y = pad_top + plot_h - step * scale
        out.append(f'<line class="grid" x1="{pad_left}" y1="{y:.1f}" '
                   f'x2="{width - pad_right}" y2="{y:.1f}" />')
        out.append(f'<text class="tick" x="{pad_left - 6}" y="{y + 4:.1f}" '
                   f'text-anchor="end">{step}</text>')

    base = pad_top + plot_h
    out.append(f'<line class="axis" x1="{pad_left}" y1="{base}" '
               f'x2="{width - pad_right}" y2="{base}" />')

    for index, column in enumerate(series):
        centre = pad_left + slot * (index + 0.5)
        if column.gap:
            out.append(f'<text class="break" x="{centre:.1f}" '
                       f'y="{base - plot_h / 2:.1f}" '
                       f'text-anchor="middle">//</text>')
            out.append(f'<text class="break" x="{centre:.1f}" y="{base + 14}" '
                       f'text-anchor="middle">·</text>')
            continue
        out.append(f'<text class="tick day" x="{centre:.1f}" y="{base + 14}" '
                   f'text-anchor="middle">{_e(column.label[5:])}</text>')
        hover = (f"{column.label}\n{column.value} newly gone\n"
                 f"{column.at_risk} still at risk\n{_pct1(column.rate)} of them")
        if not column.value:
            out.append(
                f'<g class="mark" tabindex="0" data-tip="{_e(hover)}">'
                f'<rect class="hit" x="{centre - slot / 2:.1f}" y="{pad_top}" '
                f'width="{slot:.1f}" height="{plot_h}" />'
                f'<line class="zero" x1="{centre - thickness / 2:.1f}" '
                f'y1="{base}" x2="{centre + thickness / 2:.1f}" y2="{base}" />'
                f'</g>')
            continue
        length = max(column.value * scale, 3.0)
        radius = min(4.0, length)
        left = centre - thickness / 2
        out.append(
            f'<g class="mark" tabindex="0" data-tip="{_e(hover)}">'
            f'<rect class="hit" x="{centre - slot / 2:.1f}" y="{pad_top}" '
            f'width="{slot:.1f}" height="{plot_h}" />'
            f'<path class="bar" d="M{left:.1f} {base} '
            f'V{base - length + radius:.1f} '
            f'a{radius} {radius} 0 0 1 {radius} -{radius} '
            f'h{thickness - 2 * radius:.1f} '
            f'a{radius} {radius} 0 0 1 {radius} {radius} '
            f'V{base} z" /></g>')
    out.append("</svg>")
    return "".join(out)


@dataclass
class Cell:
    value: float | None
    hover: str
    text: str


def heatmap(rows: list[tuple[str, list[Cell]]], headers: list[str], *,
            ident: str, width: int = 820) -> str:
    """Rate by platform × how old the video was when watching began.

    A grid because the question is two-dimensional and the cells are
    mostly empty: most platforms only occupy one or two age bands, and
    an empty cell has to read as "nothing here" rather than as zero.
    """
    pad_left, pad_top = 148, 30
    cell_h, gap = 34, 2
    # The columns fill the page rather than a fixed cell size: band
    # labels are whole phrases ("publication time unknown") and a
    # fixed 96px column ran them into each other.
    cell_w = max(110.0, (width - pad_left) / max(len(headers), 1))
    width = int(pad_left + cell_w * len(headers))
    height = pad_top + len(rows) * cell_h + 6

    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
           f'style="max-width:{width}px" aria-labelledby="{ident}-t">']
    out.append(f'<title id="{ident}-t">Removal rate by collection age</title>')
    for index, header in enumerate(headers):
        out.append(f'<text class="tick" x="{pad_left + cell_w * (index + 0.5)}" '
                   f'y="{pad_top - 10}" text-anchor="middle">'
                   f'{_e(header)}</text>')
    for row_index, (name, cells) in enumerate(rows):
        y = pad_top + cell_h * row_index
        out.append(f'<text class="cat" x="{pad_left - 10}" y="{y + cell_h / 2 + 4}" '
                   f'text-anchor="end">{_e(name)}</text>')
        for index, cell in enumerate(cells):
            x = pad_left + cell_w * index
            if cell.value is None:
                out.append(f'<text class="empty" '
                           f'x="{x + cell_w / 2:.0f}" '
                           f'y="{y + cell_h / 2 + 4:.0f}" '
                           f'text-anchor="middle">—</text>')
                continue
            step = min(4, int(cell.value * 5)) if cell.value < 1 else 4
            out.append(
                f'<g class="mark" tabindex="0" data-tip="{_e(cell.hover)}">'
                f'<rect class="cell s{step}" x="{x + gap}" y="{y + gap}" '
                f'width="{cell_w - 2 * gap}" height="{cell_h - 2 * gap}" '
                f'rx="3" />'
                f'<text class="in-cell t{step}" '
                f'x="{x + cell_w / 2:.0f}" y="{y + cell_h / 2 + 4:.0f}" '
                f'text-anchor="middle">{_e(cell.text)}</text></g>')
    out.append("</svg>")
    return "".join(out)


@dataclass
class Spell:
    label: str
    gone: datetime
    back: datetime
    hover: str


def intervals(spells: list[Spell], *, ident: str, width: int = 720) -> str:
    """Each reinstatement as the bracket it actually is.

    Both ends are moments the instrument looked, not moments anything
    happened, so the mark is a span between two sightings and the
    page says so underneath. A single duration drawn as a bar would be
    a claim about the platform; this is a claim about the schedule.
    """
    pad_left, pad_right, pad_top = 86, 86, 18
    row = 30
    plot = width - pad_left - pad_right
    height = pad_top + row * len(spells) + 26

    first = min(s.gone for s in spells)
    last = max(s.back for s in spells)
    reach = (last - first).total_seconds() or 1.0

    def x_of(moment: datetime) -> float:
        return pad_left + plot * (moment - first).total_seconds() / reach

    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
           f'style="max-width:{width}px" aria-labelledby="{ident}-t">']
    out.append(f'<title id="{ident}-t">Reinstatement brackets</title>')
    out.append(f'<line class="axis" x1="{pad_left}" '
               f'y1="{pad_top + row * len(spells)}" x2="{pad_left + plot}" '
               f'y2="{pad_top + row * len(spells)}" />')
    for moment, anchor in ((first, "start"), (last, "end")):
        out.append(f'<text class="tick" x="{x_of(moment):.1f}" '
                   f'y="{pad_top + row * len(spells) + 16}" '
                   f'text-anchor="{anchor}">'
                   f'{_e(_when(moment)[:16])}</text>')
    for index, spell in enumerate(spells):
        mid = pad_top + row * index + row / 2
        out.append(f'<text class="cat mono" x="{pad_left - 10}" y="{mid + 4}" '
                   f'text-anchor="end">{_e(spell.label)}</text>')
        x1, x2 = x_of(spell.gone), x_of(spell.back)
        out.append(
            f'<g class="mark" tabindex="0" data-tip="{_e(spell.hover)}">'
            f'<rect class="hit" x="{pad_left}" y="{mid - 12:.1f}" '
            f'width="{plot}" height="24" />'
            f'<line class="spell" x1="{x1:.1f}" y1="{mid:.1f}" '
            f'x2="{max(x2, x1 + 2):.1f}" y2="{mid:.1f}" />'
            f'<circle class="dot" cx="{x1:.1f}" cy="{mid:.1f}" r="4.5" />'
            f'<circle class="dot" cx="{max(x2, x1 + 2):.1f}" cy="{mid:.1f}" '
            f'r="4.5" /></g>')
        out.append(f'<text class="value" x="{pad_left + plot + 8}" '
                   f'y="{mid + 4}">{_span(spell.back - spell.gone)}</text>')
    out.append("</svg>")
    return "".join(out)


# -- the page ---------------------------------------------------------


def table(headers: list[str], rows: list[list[str]], caption: str) -> str:
    """The twin of every chart. Nothing on this page is colour-only."""
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    # The table scrolls inside its own box. Without the wrapper a
    # wide table sets the whole page's minimum width, and the layout
    # viewport grows to fit it even while the <details> is shut --
    # which is how every chart on the page ended up clipped on a
    # phone.
    return (f'<details class="twin"><summary>Table — {_e(caption)}</summary>'
            f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></details>")


def tile(label: str, value: str, note: str) -> str:
    return (f'<div class="tile"><p class="tile-label">{_e(label)}</p>'
            f'<p class="tile-value">{_e(value)}</p>'
            f'<p class="tile-note">{_e(note)}</p></div>')


@dataclass
class Page:
    """Everything the template needs, gathered before any HTML exists."""

    held: dict[str, list[Finding]] = field(default_factory=dict)
    generated: datetime | None = None
    reveal: bool = False


def _lead(page: Page) -> str:
    gone = sum(summarise(items).gone for items in page.held.values())
    tracked = sum(summarise(items).tracked for items in page.held.values())
    platforms = sum(1 for items in page.held.values() if items)
    return (
        '<section class="lead">'
        f'<p class="hero-label">Removals observed</p>'
        f'<p class="hero">{gone}</p>'
        f'<p class="hero-note">across {tracked} videos on {platforms} '
        f'platform{"s" if platforms != 1 else ""}, as of '
        f'{_e(page.generated.strftime("%Y-%m-%d") if page.generated else "—")}. '
        "Every one of them is an interval — alive when the study last "
        "looked, gone when it looked next — not a timestamp.</p>"
        "</section>"
    )


def _tiles(page: Page) -> str:
    out = []
    for platform, items in page.held.items():
        if not items:
            continue
        s = summarise(items)
        out.append(tile(
            label_for(platform),
            _pct1(s.rate),
            f"{s.gone} of {s.gone + s.alive} measured · "
            f"{s.tracked} tracked · ± {_span(s.median_uncertainty)}",
        ))
    return f'<div class="tiles">{"".join(out)}</div>'


def _horizons(page: Page) -> str:
    """The cross-platform comparable figure, faceted by horizon.

    One panel per horizon rather than one chart with three series:
    the comparison the reader wants is between platforms at a fixed
    T, and faceting keeps the page to a single hue.
    """
    panels, rows = [], []
    for age in HORIZONS:
        bars = []
        for platform, items in page.held.items():
            h = horizon(items, age)
            if not h.eligible:
                bars.append(Bar(label_for(platform), None, "", "", "no eligible videos"))
                rows.append([_span(age), label_for(platform), "0", "—", "—", "—"])
                continue
            bars.append(Bar(
                label=label_for(platform),
                value=h.rate,
                tip_text=_pct(h.rate),
                hover=(f"{label_for(platform)} · within {_span(age)}\n"
                       f"{h.removed} removed\n{h.survived} survived\n"
                       f"{h.censored} still too young to say\n"
                       f"{h.eligible} eligible"),
                note=f"n={h.eligible}",
            ))
            rows.append([_span(age), label_for(platform), str(h.eligible),
                         str(h.removed), str(h.survived), _pct1(h.rate)])
        panels.append(
            f'<figure class="panel"><figcaption>Within {_span(age)} of '
            f'publication</figcaption>'
            f'{hbars(bars, ident=f"hz{age.days}", width=410)}</figure>')
    return (
        '<section><h2>Removed within T of publication</h2>'
        '<p class="note"><strong>This is the number that compares across '
        'platforms.</strong> It counts only videos the study was already '
        'watching before T, so a video first seen at a month old is absent '
        'from the three-day question rather than counted as having survived '
        'it. <em>n</em> is how many were eligible to answer; the rest of the '
        'sample cannot.</p>'
        f'<div class="panels">{"".join(panels)}</div>'
        + table(["Horizon", "Platform", "Eligible", "Removed", "Survived",
                 "Rate"], rows, "removed within T")
        + "</section>"
    )


def _raw(page: Page) -> str:
    bars, rows = [], []
    for platform, items in page.held.items():
        s = summarise(items)
        measured = s.gone + s.alive
        bars.append(Bar(
            label=label_for(platform),
            value=s.rate,
            tip_text=_pct1(s.rate),
            hover=(f"{label_for(platform)}\n{s.gone} gone\n{s.alive} alive\n"
                   f"{s.unmeasured} never read\n"
                   f"± {_span(s.median_uncertainty)} bracket"),
            note=f"n={measured}",
        ))
        rows.append([label_for(platform), str(s.tracked), str(s.gone),
                     str(s.alive), str(s.unmeasured), _pct1(s.rate),
                     _span(s.median_uncertainty)])
    return (
        '<section><h2>Share removed, of everything watched</h2>'
        '<p class="note warn"><strong>Not comparable across platforms.</strong> '
        'Douyin is searched by tag on the day of posting; TikTok is searched '
        'by an English phrase and returns videos already weeks old. The TikTok '
        'figure is therefore a rate among videos that had already lasted a '
        'month — the ones pulled on day one were never in the sample to be '
        'found. Read it beside the collection-age grid below, and use the '
        'horizon figures above for any comparison.</p>'
        f'{hbars(bars, ident="raw")}'
        '<p class="note">Videos that were never successfully read are out of '
        'the denominator, not assumed alive. The ± column is the median width '
        'of the removal brackets: no lifetime here is known better than '
        'that.</p>'
        + table(["Platform", "Tracked", "Gone", "Alive", "Never read",
                 "Rate", "± bracket"], rows, "share removed")
        + "</section>"
    )


def _ages(page: Page) -> str:
    bands: list[str] = []
    for items in page.held.values():
        for label, _ in by_collection_age(items):
            if label not in bands:
                bands.append(label)
    if not bands:
        return ""
    rows, flat = [], []
    for platform, items in page.held.items():
        if not items:
            continue
        found = dict(by_collection_age(items))
        cells = []
        for band in bands:
            s = found.get(band)
            if s is None or not (s.gone + s.alive):
                cells.append(Cell(None, "", ""))
                continue
            cells.append(Cell(
                s.rate,
                f"{label_for(platform)} · {band}\n{s.gone} of "
                f"{s.gone + s.alive} removed\n{s.tracked} tracked",
                _pct(s.rate),
            ))
            flat.append([label_for(platform), band, str(s.tracked),
                         str(s.gone), _pct1(s.rate)])
        rows.append((label_for(platform), cells))
    legend = "".join(
        f'<span class="key"><i class="sw s{step}"></i>'
        f'{step * 20}–{step * 20 + 20}%</span>' for step in range(5))
    return (
        '<section><h2>How old each video was when watching began</h2>'
        '<p class="note">A rate is only comparable <em>within</em> a column. '
        'A search that returns month-old videos returns the ones that lasted '
        'a month, and that selection is what this grid makes visible: where a '
        'platform has no row in the youngest column, it has nothing to say '
        'about early removals.</p>'
        f'<div class="scale">{legend}</div>'
        f'{heatmap(rows, bands, ident="age")}'
        + table(["Platform", "Collection age", "Tracked", "Gone", "Rate"],
                flat, "rate by collection age")
        + "</section>"
    )


def _daily(session: Session, page: Page) -> str:
    panels, flat = [], []
    for platform, items in page.held.items():
        series = daily_hazard(session, platform, items)
        if not series:
            continue
        drawn: list[Column] = []
        previous: datetime | None = None
        for day, at_risk, events, rate in series:
            current = datetime.strptime(day, "%Y-%m-%d")
            if previous is not None and (current - previous).days > 1:
                drawn.append(Column(label="", gap=True))
            drawn.append(Column(day, events, at_risk, rate))
            flat.append([label_for(platform), day, str(at_risk), str(events),
                         _pct1(rate)])
            previous = current
        panels.append(
            f'<figure class="wide"><figcaption>{_e(label_for(platform))}'
            f'</figcaption>'
            f'{columns(drawn, ident=f"d-{platform}", title=f"New removals per observed day, {label_for(platform)}")}'
            f"</figure>")
    if not panels:
        return ""
    return (
        '<section><h2>New removals per day the study looked</h2>'
        '<p class="note"><strong>A day nobody looked is a <code>//</code>, '
        'never a zero.</strong> A zero is a claim — we looked and found '
        'nothing — and on 2026-09-27 that claim would be false. The removals '
        'of a missed day land on the next day that was observed, which is '
        'also why a single tall column is a gap in the schedule before it is '
        'an event on the platform. A flat tick on the baseline is a real '
        'zero: observed, nothing gone.</p>'
        f'{"".join(panels)}'
        + table(["Platform", "Day", "At risk", "Newly gone", "Of those at risk"],
                flat, "new removals per observed day")
        + "</section>"
    )


def _comebacks(page: Page) -> str:
    spells, flat = [], []
    for platform, items in page.held.items():
        for f in items:
            if not (f.came_back_at and f.first_gone_ever):
                continue
            spells.append(Spell(
                label=mask(f.video_id, page.reveal),
                gone=f.first_gone_ever,
                back=f.came_back_at,
                hover=(f"{label_for(platform)}\n"
                       f"gone by {_when(f.first_gone_ever)}\n"
                       f"back by {_when(f.came_back_at)}\n"
                       f"{f.disappearances} disappearance(s)"),
            ))
            flat.append([label_for(platform), mask(f.video_id, page.reveal),
                         _when(f.first_gone_ever), _when(f.came_back_at),
                         _span(f.came_back_at - f.first_gone_ever)])
    if not spells:
        return ""
    spells.sort(key=lambda s: s.gone)
    return (
        '<section><h2>Removed, then back</h2>'
        '<p class="note">Each row spans the two checks that bracket a '
        'reinstatement: the first that found the post gone, and the first '
        'after it that found it back. The width is the checking cadence, so '
        'the figure at the right is an upper bound on how long the post was '
        'actually down, never a measurement of it. At this many events this '
        'is a description, not a rate — and a post that came back is the best '
        'interview in the study, because its author knows both that they were '
        'removed and that they returned.</p>'
        f'{intervals(spells, ident="back")}'
        + table(["Platform", "Video", "Gone by", "Back by", "At most"],
                flat, "removed then reinstated")
        + "</section>"
    )


_CSS = """
:root {
  color-scheme: light;
  --plane: #f9f9f7;
  --surface-1: #fcfcfb;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11, 11, 11, 0.10);
  --series-1: #2a78d6;
  --s0: #86b6ef; --s1: #5598e7; --s2: #2a78d6; --s3: #1c5cab; --s4: #0d366b;
  --warn: #fab219;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --plane: #0d0d0d;
    --surface-1: #1a1a19;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255, 255, 255, 0.10);
    --series-1: #3987e5;
    --s0: #184f95; --s1: #256abf; --s2: #3987e5; --s3: #86b6ef; --s4: #cde2fb;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane: #0d0d0d;
  --surface-1: #1a1a19;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --grid: #2c2c2a;
  --axis: #383835;
  --border: rgba(255, 255, 255, 0.10);
  --series-1: #3987e5;
  --s0: #184f95; --s1: #256abf; --s2: #3987e5; --s3: #86b6ef; --s4: #cde2fb;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 0 16px 72px;
  background: var(--plane);
  color: var(--text-primary);
  font: 15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 900px; margin: 0 auto; }
header { padding: 40px 0 8px; }
h1 { font-size: 24px; font-weight: 600; margin: 0 0 6px; letter-spacing: -0.01em; }
h2 { font-size: 17px; font-weight: 600; margin: 0 0 10px; }
.sub { color: var(--text-secondary); margin: 0; max-width: 60ch; }
section {
  min-width: 0;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 22px;
  margin: 18px 0;
}
.lead { text-align: left; }
.hero-label {
  margin: 0; color: var(--text-secondary); font-size: 13px;
  text-transform: uppercase; letter-spacing: 0.06em;
}
.hero { margin: 2px 0 6px; font-size: 56px; line-height: 1; font-weight: 600; }
.hero-note { margin: 0; color: var(--text-secondary); max-width: 62ch; }
.tiles {
  display: grid; gap: 12px; margin: 18px 0;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 190px), 1fr));
}
.tile {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px;
}
.tile-label { margin: 0; font-size: 13px; color: var(--text-secondary); }
.tile-value { margin: 2px 0 4px; font-size: 30px; font-weight: 600; line-height: 1; }
.tile-note { margin: 0; font-size: 12px; color: var(--muted); }
.note { color: var(--text-secondary); font-size: 13.5px; margin: 0 0 14px; max-width: 72ch; }
.note.warn { border-left: 2px solid var(--warn); padding-left: 12px; }
.note code { font-size: 12.5px; }
.panels {
  display: grid; gap: 10px 24px;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 330px), 1fr));
}
.panel { margin: 0; min-width: 0; }
.wide { margin: 0 0 18px; }
figcaption {
  font-size: 12px; color: var(--text-secondary); margin-bottom: 2px;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.chart { width: 100%; height: auto; display: block; overflow: visible; }
.grid { stroke: var(--grid); stroke-width: 1; }
.axis { stroke: var(--axis); stroke-width: 1; }
.bar { fill: var(--series-1); }
.zero { stroke: var(--axis); stroke-width: 2; }
.spell { stroke: var(--series-1); stroke-width: 2; stroke-linecap: round; }
.dot { fill: var(--series-1); stroke: var(--surface-1); stroke-width: 2; }
.hit { fill: transparent; }
.mark { cursor: default; }
.mark:hover .bar, .mark:focus .bar { fill-opacity: 0.82; }
.mark:focus { outline: none; }
.mark:focus-visible .hit { stroke: var(--axis); stroke-width: 1; }
text { font: 12px system-ui, -apple-system, sans-serif; }
.tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.day { font-size: 10px; }
.cat { fill: var(--text-secondary); font-size: 12px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.value { fill: var(--text-primary); font-size: 12px; font-weight: 600; }
.note-tick { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
.empty { fill: var(--muted); font-size: 11px; font-style: italic; }
.break { fill: var(--muted); font-size: 12px; letter-spacing: -0.05em; }
.cell.s0 { fill: var(--s0); } .cell.s1 { fill: var(--s1); }
.cell.s2 { fill: var(--s2); } .cell.s3 { fill: var(--s3); }
.cell.s4 { fill: var(--s4); }
.in-cell { font-size: 12px; font-weight: 600; }
/* A label inside a fill picks ink or white by that fill's luminance,
   and the ramp inverts between modes, so the pairing has to invert
   with it rather than being fixed per step. */
.in-cell.t0, .in-cell.t1, .in-cell.t2 { fill: #0b0b0b; }
.in-cell.t3, .in-cell.t4 { fill: #fcfcfb; }
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .in-cell.t0,
  :root:where(:not([data-theme="light"])) .in-cell.t1 { fill: #fcfcfb; }
  :root:where(:not([data-theme="light"])) .in-cell.t2,
  :root:where(:not([data-theme="light"])) .in-cell.t3,
  :root:where(:not([data-theme="light"])) .in-cell.t4 { fill: #0b0b0b; }
}
:root[data-theme="dark"] .in-cell.t0,
:root[data-theme="dark"] .in-cell.t1 { fill: #fcfcfb; }
:root[data-theme="dark"] .in-cell.t2,
:root[data-theme="dark"] .in-cell.t3,
:root[data-theme="dark"] .in-cell.t4 { fill: #0b0b0b; }
.scale { display: flex; gap: 14px; flex-wrap: wrap; margin: 0 0 12px; }
.key { font-size: 11.5px; color: var(--text-secondary); display: flex;
       align-items: center; gap: 5px; }
.sw { width: 14px; height: 10px; border-radius: 2px; display: inline-block; }
.sw.s0 { background: var(--s0); } .sw.s1 { background: var(--s1); }
.sw.s2 { background: var(--s2); } .sw.s3 { background: var(--s3); }
.sw.s4 { background: var(--s4); }
.twin { margin-top: 14px; }
.scroll { overflow-x: auto; max-width: 100%; }
.twin summary {
  cursor: pointer; font-size: 12.5px; color: var(--text-secondary);
  padding: 4px 0;
}
table { border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 12.5px; }
th, td {
  text-align: right; padding: 5px 8px; border-bottom: 1px solid var(--grid);
  font-variant-numeric: tabular-nums;
}
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
th { color: var(--text-secondary); font-weight: 600; white-space: nowrap; }
footer {
  max-width: 900px; margin: 0 auto; padding-top: 10px;
  color: var(--muted); font-size: 12.5px;
}
footer p { max-width: 74ch; }
#tip {
  position: fixed; pointer-events: none; opacity: 0; z-index: 9;
  background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 10px; font-size: 12.5px; line-height: 1.45;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.14); max-width: 260px;
  transition: opacity 90ms linear;
}
#tip b { font-size: 13px; }
@media (max-width: 640px) {
  .hero { font-size: 44px; }
  section { padding: 16px; }
}
@media print {
  body { background: #fff; }
  .twin[open] summary { display: none; }
  section { break-inside: avoid; }
}
"""

#: Labels come from the database, so they reach the DOM as text nodes
#: and never as markup. There is nothing else here: the page is drawn
#: server-side and this only reads what is already in the attribute.
_JS = """
(function () {
  var tip = document.getElementById('tip');
  function show(target, x, y) {
    var text = target.getAttribute('data-tip') || '';
    tip.textContent = '';
    text.split('\\n').forEach(function (line, index) {
      if (index) { tip.appendChild(document.createElement('br')); }
      var node = document.createElement(index ? 'span' : 'b');
      node.textContent = line;
      tip.appendChild(node);
    });
    tip.style.opacity = '1';
    var box = tip.getBoundingClientRect();
    var left = Math.min(x + 14, window.innerWidth - box.width - 8);
    var top = Math.max(8, y - box.height - 12);
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }
  function hide() { tip.style.opacity = '0'; }
  document.addEventListener('pointermove', function (event) {
    var mark = event.target.closest('.mark');
    if (mark) { show(mark, event.clientX, event.clientY); } else { hide(); }
  });
  document.addEventListener('pointerleave', hide);
  document.addEventListener('focusin', function (event) {
    var mark = event.target.closest('.mark');
    if (!mark) { return hide(); }
    var box = mark.getBoundingClientRect();
    show(mark, box.left + box.width / 2, box.top + box.height / 2);
  });
  document.addEventListener('focusout', hide);
})();
"""


def build(session: Session, *, reveal: bool = False,
          generated: datetime | None = None) -> str:
    """The whole page, as one string."""
    page = Page(
        held={p: own(session, p) for p in PLATFORMS},
        generated=local(generated or clock_now()),
        reveal=reveal,
    )
    stamp = page.generated.strftime("%Y-%m-%d %H:%M") if page.generated else "—"
    body = "".join([
        "<header><h1>Takedown observatory</h1>",
        '<p class="sub">Chinese-language WLW posts on Douyin, TikTok and '
        "YouTube, watched daily for removal. A snapshot, not a live view: "
        f"everything below was read out of the collection at {_e(stamp)} "
        "and will not change.</p></header>",
        _lead(page),
        _tiles(page),
        _horizons(page),
        _raw(page),
        _ages(page),
        _daily(session, page),
        _comebacks(page),
    ])
    footer = (
        "<footer>"
        "<p><strong>How to read a removal here.</strong> The study checks each "
        "post about once a day. A removal is therefore known as a bracket — "
        "alive at one check, gone at the next — and every figure on this page "
        "carries that bracket rather than hiding it in a timestamp. There is "
        "no median time to removal anywhere on the page: a median needs half "
        "the sample removed, and below that it is undefined rather than "
        "long.</p>"
        "<p><strong>What is missing is on purpose.</strong> No captions, no "
        "account names, and video ids are shown as their last four digits. "
        "These are posts by identifiable people on a sensitive topic; the "
        "page is aggregate so that it can be shared without carrying them "
        "along. The per-post detail stays in the admin dashboard and the "
        "local CSV export.</p>"
        f"<p>Generated by <code>app.report</code> from the collection "
        f"database at {_e(stamp)} "
        f"({_e(clock_today().isoformat())} local). Methods, and every "
        "caveat behind these charts, in <code>docs/METHODOLOGY.md</code>.</p>"
        "</footer>"
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Takedown observatory</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<main>{body}</main>{footer}"
        '<div id="tip" role="status" aria-live="polite"></div>'
        f"<script>{_JS}</script>"
        "</body></html>\n"
    )


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="takedowns.html",
                        help="where to write the page")
    parser.add_argument(
        "--identifiers", action="store_true",
        help="print whole video ids instead of their last four digits",
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        html = build(session, reveal=args.identifiers)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(html)
    print(f"{len(html) / 1024:.0f} KB written to {args.out}")
    if args.identifiers:
        print("Whole video ids are in this file. Do not post it anywhere.")


if __name__ == "__main__":  # pragma: no cover
    main()
