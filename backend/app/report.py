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

from . import labels
from .analyse import (
    PLATFORMS,
    author_names,
    corpus_captions,
    daily_hazard,
    own,
)
from .clock import local, now as clock_now, today as clock_today
from .survival import (
    Curve,
    Finding,
    by_collection_age,
    horizon,
    kaplan_meier,
    quartiles,
    removal_ages,
    summarise,
)

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

#: The platform the study is actually about, in the two formats it
#: serves. Everything above the fold is these two.
DOUYIN: tuple[str, ...] = ("douyin", "douyin_note")
#: Kept, reported, and deliberately not charted beside Douyin.
CONTEXT: tuple[str, ...] = ("tiktok", "youtube")

#: What each account-name marker says, for a reader without Chinese.
_MARKS = {
    "throttled": "限流 (throttled)",
    "replacement": "新号 (rebuilt account)",
    "spare": "小号 (spare account)",
    "banned": "被封 (banned)",
}

PRETTY = {
    "douyin": "Douyin video",
    "douyin_note": "Douyin 图文 (note)",
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


@dataclass
class Slice:
    label: str
    count: int
    hover: str


def pie(slices: list[Slice], *, ident: str, title: str,
        width: int = 400) -> str:
    """Part-to-whole, for categories that really do partition the whole.

    The slices here are **combinations**, not tags. A caption can
    carry `#wlw` and `#lwl` at once, and a pie of per-tag counts would
    sum past 100% while looking as though it did not. So each post
    lands in exactly one slice, named for the whole set of tags it
    carries, and the per-tag totals -- which do overlap -- stay in the
    table underneath where overlapping is legible.

    Six slices at most: past that adjacent wedges blur and the colour
    order stops being the safety mechanism it is. The tail folds into
    one named slice rather than becoming a seventh hue.
    """
    total = sum(s.count for s in slices) or 1
    radius, cx, cy = 78.0, 92.0, 96.0
    height = 200

    out = [f'<svg class="chart pie" viewBox="0 0 {width} {height}" role="img" '
           f'style="max-width:{width}px" aria-labelledby="{ident}-t">']
    out.append(f'<title id="{ident}-t">{_e(title)}</title>')

    angle = -90.0
    for index, piece in enumerate(slices):
        share = piece.count / total
        sweep = share * 360
        if sweep <= 0:
            continue
        if share >= 0.999:
            out.append(f'<circle class="slice c{index + 1}" cx="{cx}" '
                       f'cy="{cy}" r="{radius}" />')
        else:
            out.append(f'<path class="slice c{index + 1}" '
                       f'd="{_wedge(cx, cy, radius, angle, angle + sweep)}" />')
        angle += sweep

    # The legend carries identity; the labels carry the numbers. A
    # percentage written on a 2% wedge does not fit inside it, so none
    # of them are written inside.
    y = 26.0
    for index, piece in enumerate(slices):
        share = piece.count / total
        out.append(
            f'<g class="mark" tabindex="0" data-tip="{_e(piece.hover)}">'
            f'<rect class="hit" x="{cx + radius + 8}" y="{y - 13:.0f}" '
            f'width="{width - cx - radius - 16}" height="22" />'
            f'<rect class="key-swatch c{index + 1}" x="{cx + radius + 14}" '
            f'y="{y - 9:.0f}" width="11" height="11" rx="2" />'
            f'<text class="cat" x="{cx + radius + 32}" y="{y:.0f}">'
            f'{_e(piece.label)}</text>'
            f'<text class="value" x="{width - 8}" y="{y:.0f}" '
            f'text-anchor="end">{share * 100:.0f}%</text></g>')
        y += 24
    out.append("</svg>")
    return "".join(out)


def _wedge(cx: float, cy: float, r: float, start: float, end: float) -> str:
    """One slice, inset by a hairline so the surface does the separating."""
    import math

    # A 1.2 degree inset on each side leaves a surface-coloured gap of
    # about 2px at this radius -- the spacer, rather than a stroke
    # drawn around every wedge.
    start, end = start + 1.2, end - 1.2
    if end <= start:
        end = start + 0.2
    x1 = cx + r * math.cos(math.radians(start))
    y1 = cy + r * math.sin(math.radians(start))
    x2 = cx + r * math.cos(math.radians(end))
    y2 = cy + r * math.sin(math.radians(end))
    large = 1 if end - start > 180 else 0
    return (f"M{cx:.1f} {cy:.1f} L{x1:.1f} {y1:.1f} "
            f"A{r} {r} 0 {large} 1 {x2:.1f} {y2:.1f} Z")


def _groups(rows: list[list[str]], cap: int = 6) -> list[Slice]:
    """Exact tag-set combinations, commonest first, tail folded into one."""
    counted: dict[str, int] = {}
    for tags in rows:
        counted[" + ".join(tags)] = counted.get(" + ".join(tags), 0) + 1
    order = sorted(counted.items(), key=lambda pair: -pair[1])
    head, tail = order[:cap - 1], order[cap - 1:]
    total = sum(counted.values()) or 1
    out = [
        Slice(name, n, f"{name}\n{n} post(s)\n{n / total * 100:.1f}%")
        for name, n in head
    ]
    if tail:
        rest = sum(n for _, n in tail)
        out.append(Slice(
            f"其他 (other, {len(tail)})", rest,
            "其他 (other)\n" + "\n".join(f"{name}: {n}" for name, n in tail)))
    return out


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
    kind = "tile-value" if value[:1].isdigit() else "tile-value words"
    return (f'<div class="tile"><p class="tile-label">{_e(label)}</p>'
            f'<p class="{kind}">{_e(value)}</p>'
            f'<p class="tile-note">{_e(note)}</p></div>')


@dataclass
class Page:
    """Everything the template needs, gathered before any HTML exists."""

    held: dict[str, list[Finding]] = field(default_factory=dict)
    generated: datetime | None = None
    reveal: bool = False


@dataclass
class Counted:
    """Share removed by each age, counted rather than estimated.

    `points` is (age in days, removed, answerable, unknown).
    `answerable` is the posts whose fate at that age is known: watched
    from before it, and either already gone or watched past it. A post
    collected two days ago cannot say anything about what happens by
    day seven, so it is out of that denominator rather than counted as
    a survivor of it. `unknown` is the rest -- still up, but not
    watched long enough to answer.

    Counting this way is honest at every age but not unbiased at every
    age: a post removed on day two is known at every later age, while
    a surviving post has to be watched that long to count at all. So
    as the age grows the known set fills up with removals and the
    share climbs towards 100%. That is an artefact of how long
    collection has been running, not a property of the platform.

    So the floor sits on the survivors, not on the denominator: a
    point is drawn only once `FLOOR` posts have actually been watched
    past that age. Where none have, the only posts that can answer
    are the ones already taken down and the share is 100% by
    construction -- on this corpus 图文 reads 100% at fourteen days
    off fifteen removals and no survivors, which is a statement about
    how long collection has run and nothing else. A floor on the
    denominator instead of the survivors let exactly those points
    through.

    Above the floor, `firm` says whether most of the eligible posts
    have an answer yet (`answerable >= unknown`). The chart draws the
    firm stretch solid and the rest dashed: dropping the thin ages
    altogether cut 图文, collected in one recent burst, back to a
    single day, which said less than showing it thin.
    """

    #: Posts that have to have outlived an age before it is drawn.
    FLOOR = 8

    name: str
    slot: int
    points: list[tuple[float, int, int]] = field(default_factory=list)

    @property
    def shown(self) -> list[tuple[float, int, int, int]]:
        """The points with enough survivors to be able to come out low."""
        return [p for p in self.points if p[2] - p[1] >= self.FLOOR]

    def firm(self, age: float) -> bool:
        """Do most of the eligible posts have an answer at this age?"""
        for at, _, answerable, unknown in self.points:
            if at == age:
                return bool(answerable) and answerable >= unknown
        return False

    @property
    def reach(self) -> float:
        return max((age for age, _, _, _ in self.shown), default=1.0)

    def share(self, age: float) -> float | None:
        for at, removed, answerable, _ in self.points:
            if at == age and answerable:
                return removed / answerable
        return None

    def answerable(self, age: float) -> int:
        return next((n for at, _, n, _ in self.points if at == age), 0)


def counted(name: str, slot: int, items: list[Finding],
            ages: list[float]) -> Counted:
    """Observed share removed at each age, via `horizon`.

    No estimator and no extrapolation: at every age this is a count
    over a denominator that is stated on the chart. It is the same
    question the horizon table asked, asked at more ages.
    """
    out = Counted(name=name, slot=slot)
    for age in ages:
        window = horizon(items, timedelta(days=age))
        out.points.append((age, window.removed,
                           window.removed + window.survived, window.censored))
    return out


def removal_chart(lines: list[Counted], *, ident: str,
                  width: int = 820, height: int = 300) -> str:
    """Share removed by age since publication, counted at each age.

    Rising from zero rather than falling from one, so the baseline is
    a real zero and the axis can stop at the top of the data without
    truncating anything.

    **Nothing here is estimated.** Each point is removed over
    answerable, and the answerable counts are printed under the axis.
    Where that number is small the point is a handful of posts, which
    is why it is on the chart rather than in a footnote.
    """
    pad_left, pad_right, pad_top = 46, 108, 14
    pad_bottom = 46 + 18 * len(lines)
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    peak = max(
        [share for line in lines for age, _, _, _ in line.shown
         if (share := line.share(age)) is not None] or [0.1])
    top = max(0.1, min(1.0, (int(peak * 10) + 1) / 10))
    reach = max([line.reach for line in lines] or [1.0])

    def x_of(days: float) -> float:
        return pad_left + plot_w * min(days / reach, 1.0)

    def y_of(share: float) -> float:
        return pad_top + plot_h * (1 - share / top)

    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
           f'style="max-width:{width}px" aria-labelledby="{ident}-t">']
    out.append(f'<title id="{ident}-t">Share removed by age since '
               f'publication</title>')

    rungs = 4
    for index in range(rungs + 1):
        share = top * index / rungs
        y = y_of(share)
        out.append(f'<line class="grid" x1="{pad_left}" y1="{y:.1f}" '
                   f'x2="{pad_left + plot_w}" y2="{y:.1f}" />')
        out.append(f'<text class="tick" x="{pad_left - 6}" y="{y + 4:.1f}" '
                   f'text-anchor="end">{share * 100:.0f}%</text>')
    for age in sorted({age for line in lines for age, _, _, _ in line.shown}):
        out.append(f'<text class="tick" x="{x_of(age):.1f}" '
                   f'y="{pad_top + plot_h + 18:.0f}" '
                   f'text-anchor="middle">{age:g}d</text>')
    out.append(f'<line class="axis" x1="{pad_left}" y1="{pad_top + plot_h}" '
               f'x2="{pad_left + plot_w}" y2="{pad_top + plot_h}" />')

    row = pad_top + plot_h + 48
    out.append(f'<text class="tick" x="{pad_left - 6}" y="{row - 14:.0f}" '
               f'text-anchor="end">posts</text>')
    for line in lines:
        for age, _, answerable, _ in line.shown:
            out.append(
                f'<text class="tick risk" x="{x_of(age):.1f}" '
                f'y="{row:.0f}" text-anchor="middle">{answerable}</text>')
        out.append(f'<rect class="key-swatch c{line.slot}" '
                   f'x="{pad_left - 15}" y="{row - 9:.0f}" '
                   f'width="9" height="9" rx="2" />')
        row += 18

    labelled: list[float] = []
    for line in lines:
        drawn = [(age, share) for age, _, _, _ in line.shown
                 if (share := line.share(age)) is not None]
        if not drawn:
            continue
        # The leading run where most eligible posts have an answer is
        # drawn solid; the thin tail carries on dashed from the last
        # firm point, so the line is continuous but says where it
        # stops being well supported.
        firm = 0
        while firm < len(drawn) and line.firm(drawn[firm][0]):
            firm += 1

        def trace(part: list[tuple[float, float]], klass: str) -> None:
            if len(part) < 2:
                return
            path = " ".join(
                f"{'M' if index == 0 else 'L'}"
                f"{x_of(age):.1f} {y_of(share):.1f}"
                for index, (age, share) in enumerate(part))
            out.append(f'<path class="{klass} c{line.slot}" d="{path}" />')

        trace(drawn[:firm], "line")
        trace(drawn[max(firm - 1, 0):], "line thin")
        for age, share in drawn:
            removed = next(r for at, r, _, _ in line.points if at == age)
            answerable = line.answerable(age)
            solid = line.firm(age)
            hover = (f"{line.name}\nby day {age:g}: {removed} of "
                     f"{answerable} removed ({share * 100:.0f}%)\n"
                     + ("counted, not estimated" if solid else
                        "counted, but most posts this old are not "
                        "watched long enough yet"))
            out.append(
                f'<g class="mark" tabindex="0" data-tip="{_e(hover)}">'
                f'<circle class="hit" cx="{x_of(age):.1f}" '
                f'cy="{y_of(share):.1f}" r="12" />'
                f'<circle class="dot{"" if solid else " hollow"} '
                f'c{line.slot}" cx="{x_of(age):.1f}" '
                f'cy="{y_of(share):.1f}" r="3.5" /></g>')
        last_age, last_share = drawn[-1]
        y = y_of(last_share) + 4
        while any(abs(y - taken) < 15 for taken in labelled):
            y += 15
        labelled.append(y)
        out.append(f'<text class="end-label c{line.slot}" '
                   f'x="{x_of(last_age) + 8:.1f}" y="{y:.1f}">'
                   f'{_e(line.name)} {last_share * 100:.0f}%</text>')

    out.append("</svg>")
    return "".join(out)


def _day_ticks(reach: float) -> list[float]:
    step = 1.0
    for candidate in (1, 2, 3, 5, 7, 10, 14, 30, 60):
        step = candidate
        if reach / candidate <= 7:
            break
    ticks, day = [], 0.0
    while day <= reach:
        ticks.append(day)
        day += step
    return ticks


def _rate_tile(label: str, items: list[Finding]) -> str:
    s = summarise(items)
    measured = s.gone + s.alive
    return tile(label, _pct1(s.rate), f"{s.gone} of {measured} watched")


def _douyin(session: Session, page: Page) -> str:
    """The core platform, and the only one with a same-day sample."""
    video = page.held.get("douyin", [])
    notes = page.held.get("douyin_note", [])
    both = video + notes
    whole = kaplan_meier(both)
    ages = [1, 2, 3, 5, 7, 10, 14, 21, 30]
    curves = [
        counted("视频 (video)", 1, video, ages),
        counted("图文 (note)", 2, notes, ages),
    ]

    lasted = removal_ages(both)
    spread = quartiles(lasted)
    tiles = "".join([
        _rate_tile("视频 (video)", video),
        _rate_tile("图文 (note)", notes),
        tile("The removed posts lasted",
             _span(spread[1]) if spread else "—",
             f"median of {len(lasted)} removals; middle half "
             f"{_span(spread[0])}–{_span(spread[2])}" if spread
             else "nothing removed yet"),
        # Named for what it does to the reader's reading, not for
        # what it is in the data: "checking bracket" is this study's
        # own vocabulary and told the first reader nothing.
        tile("Removal times known to within", _span(whole.resolution),
             "the gap between the check that saw it up and the one "
             "that saw it gone"),
    ])

    # The table is the chart's own numbers, with the denominator
    # beside each one rather than under the axis.
    # The table is the chart's twin, so it holds the same ages and
    # drops the same ones: a cell for an age with no survivors would
    # read 100% and mean only that collection has not run that long.
    drawable = {age for line in curves for age, _, _, _ in line.shown}
    rows = []
    for days in ages:
        if days not in drawable:
            continue
        row = [f"{days}d"]
        for line in curves:
            share = line.share(days)
            if days not in {age for age, _, _, _ in line.shown}:
                share = None
            # A dagger where the chart goes dashed, so the table twin
            # carries the same warning the line does.
            thin = "" if line.firm(days) else " †"
            row.append("—" if share is None else f"{share * 100:.0f}%{thin}")
            row.append("—" if share is None else str(line.answerable(days)))
        rows.append(row)

    return (
        '<section class="core"><h2>抖音 (Douyin) — removal by age of post</h2>'
        f'<div class="tiles">{tiles}</div>'
        '<div class="scale">'
        '<span class="key"><i class="rule c1"></i>视频 (video)</span>'
        '<span class="key"><i class="rule c2"></i>图文 (note)</span>'
        '<span class="key"><i class="rule dash"></i>'
        '虚线 (dashed) = 多数帖子还没到这个年龄</span></div>'
        f'{removal_chart(curves, ident="km")}'
        '<p class="note"><strong>Counted, not estimated.</strong> Each '
        'point is "of the posts this question can be asked of, how many were '
        'gone by this age" — and the row under the axis is how many posts '
        'that was. A post collected two days ago cannot say anything about '
        'what happens by day seven, so it is left out of that denominator '
        'rather than counted as having survived it. Where the number under a '
        'point is small, the point is a handful of posts. '
        '<strong>Dashed means thin:</strong> past that point most posts that '
        'old are still up but have not been watched long enough to answer, '
        'so the posts that do answer are mostly the ones already taken down '
        'and the line drifts up for that reason rather than any other. Read '
        'the solid stretch as the measurement and the dashed stretch as the '
        'most that can be said so far. Each line ends where fewer than '
        f'{Counted.FLOOR} posts have been watched past that age at all: '
        'past there the only posts that can answer are the ones already '
        'taken down, so the share would read 100% however rarely posts are '
        'actually removed.</p>'
        + table(["Age", "视频 removed", "视频 watched", "图文 removed",
                 "图文 watched"], rows, "share removed by age")
        + '<p class="note">† the dashed part of the chart: fewer than half '
          'the eligible posts have reached this age yet, so the share is the '
          'most that can be said so far rather than a measurement.</p>'

        + "</section>"
    )


def _median_line(whole: Curve, lasted: list[timedelta]) -> str:
    """The sentence that keeps the two medians from being confused.

    The tile reports the median of the removals that have happened.
    That number is not how long a post lasts: the posts destined for
    a slow removal have not had it yet, so they are missing from it
    and it drifts upward as the study runs. The curve is the estimate
    that keeps them in, and what it says about a median is usually
    that there is not one yet.
    """
    reached = whole.quantile(0.5)
    if reached:
        return (f"Over the whole corpus, half of all posts are gone by "
                f"{_span(reached)}.")
    quarter = whole.quantile(0.25)
    tail = (f"a quarter of all posts are gone by {_span(quarter)}"
            if quarter else "not even a quarter of all posts has gone")
    return (f"The tile above describes the {len(lasted)} removals that have "
            f"happened, not how long a post lasts — the slow removals have "
            f"not happened yet. Across the whole corpus, {tail}, and the "
            f"halfway point has not been reached.")


def _at_risk(curve: Curve, age: timedelta) -> int:
    held = 0
    for step in curve.steps:
        if step.age > age:
            break
        held = step.at_risk
    return held


def _content(session: Session, page: Page) -> str:
    """What the corpus says about itself, in the words its authors used.

    Only the tag axes are here. They are string matching (see
    `app/labels.py`), so they are exact, free and reproducible. The
    content category -- what a post is *about* -- needs a reader, is
    not coded yet, and will arrive as its own block rather than as a
    guess dressed up as a chart.
    """
    corpus = corpus_captions(session)
    if not corpus:
        return ""

    gone = {
        f.video_id for p in DOUYIN for f in page.held.get(p, []) if f.is_gone
    }
    total = len(corpus)
    with_text = [row for row in corpus if row[2]]
    blank = total - len(with_text)

    wlw_rows = [labels.wlw_tags(text) for _, _, text in with_text]
    tph_rows = [labels.tph_tags(text) for _, _, text in with_text]
    flagged = sum(1 for _, _, text in with_text if labels.compliance(text))

    # Moderation as the authors themselves report it. Two registers:
    # inside a post, and in the account name -- which is the stronger
    # of the two, because it is not a complaint in one caption but a
    # person restructuring how they are findable and leaving it that
    # way.
    named = author_names(session)
    marks: dict[str, set[str]] = {}
    for _, video_id, _ in corpus:
        for kind in labels.account_marks(named.get(video_id)):
            marks.setdefault(kind, set()).add(video_id)
    renamed = len({v for ids in marks.values() for v in ids})

    # How many people this corpus is, rather than how many posts. A
    # sampling fact first -- 400 posts from 40 accounts is a different
    # object from 400 posts by 400 people -- and an interview fact
    # second, since the interview frame is accounts, not posts.
    named = author_names(session)
    accounts = {named[v] for _, v, _ in corpus if named.get(v)}
    busiest = 0
    if accounts:
        per: dict[str, int] = {}
        for _, video_id, _ in corpus:
            who = named.get(video_id)
            if who:
                per[who] = per.get(who, 0) + 1
        busiest = max(per.values())

    tiles = "".join([
        tile("Posts in the corpus", str(total),
             f"{blank} carry no caption at all"),
        tile("Caption speaks to the moderator", str(flagged),
             "#无不良倾向 (no bad influence), 被屏了重发 (blocked, "
             "reposted), 解封 (unbanned)"),
        tile("Accounts behind them", str(len(accounts)),
             f"at most {busiest} post(s) from any one account"
             if accounts else "no author name recorded yet"),
    ])

    def per_tag(rows: list[list[str]], kind) -> str:
        counted: dict[str, int] = {}
        removed: dict[str, int] = {}
        for (platform, video_id, text), tags in zip(with_text, rows):
            for tag in tags:
                counted[tag] = counted.get(tag, 0) + 1
                removed[tag] = removed.get(tag, 0) + (video_id in gone)
        return table(
            ["Tag", "Posts", "Share", "Removed", "Of those"],
            [[name, str(n), f"{n / len(with_text) * 100:.1f}%",
              str(removed[name]),
              f"{removed[name] / n * 100:.0f}%" if n else "—"]
             for name, n in sorted(counted.items(), key=lambda p: -p[1])],
            kind,
        )

    return (
        '<section><h2>抖音 (Douyin) — what the posts call themselves</h2>'
        f'<div class="tiles">{tiles}</div>'
        '<div class="panels">'
        '<figure class="panel"><figcaption>女同标记 (community tags)'
        '</figcaption>'
        f'{pie(_groups(wlw_rows), ident="pw", title="Community tags")}'
        "</figure>"
        '<figure class="panel"><figcaption>角色词 (role vocabulary)'
        '</figcaption>'
        f'{pie(_groups(tph_rows), ident="pt", title="Role vocabulary")}'
        "</figure></div>"
        '<p class="note">Each post sits in exactly one slice, named for '
        'the whole set of tags it carries — a post tagged both <code>#wlw</code> '
        'and <code>#lwl</code> is in the “wlw + lwl” slice, not counted twice. '
        'The tables below give the per-tag totals, which do overlap. '
        '<strong>Hairstyle and prettiness tags are not role vocabulary</strong> '
        'and are in none of these counts: <code>#短发</code> is a haircut, and '
        'reading it as a role is a stereotype rather than an observation.</p>'
        + per_tag(wlw_rows, "community tags")
        + per_tag(tph_rows, "role vocabulary")
        + '<p class="note">The removal columns are descriptive. Several of '
        'these groups hold a handful of posts, nothing here is a test, and '
        'no difference between them should be read as one yet.</p>'
        '<p class="note"><strong>“Caption speaks to the moderator” is what '
        'the authors say happened to them, not what this study '
        'observed</strong> — the observed removals are in the Overview. '
        'Account names say it too (限流版 throttled edition, 新号 rebuilt '
        'account); that count is in the label export rather than here, '
        'since so far it is a handful. The names themselves are never '
        'printed: these are the accounts least able to afford it.</p>'
        "</section>"
    )


def _daily(session: Session, page: Page) -> str:
    """New removals per day, Douyin only -- the other two are too thin."""
    panels, flat = [], []
    for platform in DOUYIN:
        items = page.held.get(platform, [])
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
        '<section><h2>New removals, per day the study looked</h2>'
        '<p class="note">A <code>//</code> is a day nobody looked; its '
        'removals land on the next day that was. A tick on the baseline is a '
        'real zero.</p>'
        f'{"".join(panels)}'
        + table(["Platform", "Day", "At risk", "Newly gone", "Of those at risk"],
                flat, "new removals per observed day")
        + "</section>"
    )


def _context(page: Page) -> str:
    """TikTok and YouTube as context, deliberately not as a comparison.

    They were kept out of the charts above on purpose. Both samples
    are small and both were collected weeks after publication, so a
    bar beside Douyin's would invite exactly the comparison the
    sampling cannot support. A table states what they are and stops.
    """
    rows = []
    for platform in CONTEXT:
        items = page.held.get(platform, [])
        if not items:
            continue
        s = summarise(items)
        ages = by_collection_age(items)
        oldest = ages[-1][0] if ages else "—"
        rows.append([label_for(platform), str(s.tracked), str(s.gone),
                     _pct1(s.rate), oldest])
    if not rows:
        return ""
    return (
        '<section class="aside"><h2>TikTok and YouTube, for context only</h2>'
        '<p class="note">Not charted beside Douyin, and not comparable to it. '
        'Both were found by searching phrases that return posts already weeks '
        'old, so each sample is made of posts that had <em>already</em> '
        'survived — the ones removed in week one were never there to be '
        'collected.</p>'
        + table(["Platform", "Tracked", "Gone", "Rate", "Typical age when found"],
                rows, "context platforms")
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
        '<p class="note">From the check that found the post gone to the one '
        'that found it back. The figure on the right is an upper bound on how '
        'long it was down, not a measurement of it.</p>'
        f'{intervals(spells, ident="back")}'
        + table(["Platform", "Video", "Gone by", "Back by", "At most"],
                flat, "removed then reinstated")
        + "</section>"
    )


def _method() -> str:
    """Everything that used to sit between the reader and the charts."""
    return (
        '<details class="method"><summary>How to read this page</summary>'
        "<p><strong>A removal is a bracket, not a time.</strong> Each post is "
        "checked about once a day, so what the data knows is that it was up at "
        "one check and gone at the next. The curve places each removal in the "
        "middle of its bracket; the <em>checking bracket</em> tile says how "
        "wide those brackets typically are, and nothing here is sharper than "
        "that.</p>"
        "<p><strong>Watching starts when the study found the post, not when "
        "it was published.</strong> A removal before that was never "
        "observable, so a post joins the curve at the age it was collected "
        "rather than at zero. Without this, every sample of older posts would "
        "look unkillable: it only contains posts that lasted long enough to "
        "be found.</p>"
        "<p><strong>A median needs half the sample removed.</strong> Below "
        "that the median is not long, it is undefined, and the tile says "
        "<em>not reached</em> rather than inventing a number. The quarter "
        "point is reported instead when the curve has crossed it.</p>"
        "<p><strong>A day the study did not run is a gap, never a zero.</strong> "
        "A zero claims we looked and found nothing. On 2026-09-27 nobody "
        "looked, so that day is a break in the axis and its removals surface "
        "on the next day that was observed.</p>"
        "<p><strong>Aggregates only.</strong> No captions, no account names, "
        "and video ids cut to six digits. These are posts by identifiable "
        "people on a sensitive topic. The per-post detail stays in the "
        "key-gated dashboard and the local CSV.</p>"
        "<p>Full method, and every caveat behind these figures, in "
        "<code>docs/METHODOLOGY.md</code>.</p></details>"
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
  --series-2: #eb6834;
  --cat-1: #2a78d6; --cat-2: #eb6834; --cat-3: #1baf7a;
  --cat-4: #eda100; --cat-5: #e87ba4; --cat-6: #008300;
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
    --series-2: #d95926;
    --cat-1: #3987e5; --cat-2: #d95926; --cat-3: #199e70;
    --cat-4: #c98500; --cat-5: #d55181; --cat-6: #008300;
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
  --series-2: #d95926;
  --cat-1: #3987e5; --cat-2: #d95926; --cat-3: #199e70;
  --cat-4: #c98500; --cat-5: #d55181; --cat-6: #008300;
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
/* Tabs. The radio lives off-screen rather than display:none, so it
   keeps keyboard focus and the arrow keys still move between tabs. */
.tab-radio { position: absolute; opacity: 0; pointer-events: none; }
.tab-strip {
  display: flex; gap: 4px; margin: 20px 0 0; flex-wrap: wrap;
  border-bottom: 1px solid var(--border);
}
.tab {
  cursor: pointer; padding: 9px 14px; font-size: 13.5px; font-weight: 600;
  color: var(--text-secondary); border-radius: 8px 8px 0 0;
  border: 1px solid transparent; border-bottom: none;
  margin-bottom: -1px; white-space: nowrap;
}
.tab:hover { color: var(--text-primary); background: var(--surface-1); }
.tabs > div[class^="panel-"] { display: none; }
#tab-overview:checked ~ .panel-overview,
#tab-analysis:checked ~ .panel-analysis { display: block; }
#tab-overview:checked ~ .tab-strip [for="tab-overview"],
#tab-analysis:checked ~ .tab-strip [for="tab-analysis"] {
  color: var(--text-primary);
  background: var(--surface-1);
  border-color: var(--border);
}
.tab-radio:focus-visible + .tab-strip .tab,
#tab-overview:focus-visible ~ .tab-strip [for="tab-overview"],
#tab-analysis:focus-visible ~ .tab-strip [for="tab-analysis"] {
  outline: 2px solid var(--series-1); outline-offset: 2px;
}
.core { border-color: var(--axis); }
.method { max-width: 900px; margin: 18px auto 0; color: var(--text-secondary);
          font-size: 13px; }
.method summary { cursor: pointer; padding: 6px 0; }
.method p { max-width: 76ch; }
.aside h2 { font-size: 15px; }
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
.tile-value { margin: 2px 0 4px; font-size: 30px; font-weight: 600; line-height: 1.1; }
/* "not reached" is an answer, not a number: at 30px it shouts over
   the rates beside it, which are the figures the row is for. */
.tile-value.words { font-size: 19px; }
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
.line { fill: none; stroke-width: 2; stroke-linejoin: round;
        stroke-linecap: round; }
.line.c1, .dot.c1 { stroke: var(--series-1); }
.dot.c1 { fill: var(--series-1); }
.line.c2, .dot.c2 { stroke: var(--series-2); }
.dot.c2 { fill: var(--series-2); }
.dot { stroke: var(--surface-1); stroke-width: 2; }
.line.thin { stroke-dasharray: 5 4; }
.dot.hollow { fill: var(--surface-1); }
.pie .slice { stroke: none; }
.slice.c1 { fill: var(--cat-1); } .slice.c2 { fill: var(--cat-2); }
.slice.c3 { fill: var(--cat-3); } .slice.c4 { fill: var(--cat-4); }
.slice.c5 { fill: var(--cat-5); } .slice.c6 { fill: var(--cat-6); }
.key-swatch.c1 { fill: var(--cat-1); } .key-swatch.c2 { fill: var(--cat-2); }
.key-swatch.c3 { fill: var(--cat-3); } .key-swatch.c4 { fill: var(--cat-4); }
.key-swatch.c5 { fill: var(--cat-5); } .key-swatch.c6 { fill: var(--cat-6); }
.mark:hover .slice, .mark:focus .slice { fill-opacity: 0.85; }
.end-label { font-size: 12px; font-weight: 600; fill: var(--text-secondary); }
.risk { font-size: 10px; }
.mark:hover .dot, .mark:focus .dot { r: 5; }
.zero { stroke: var(--axis); stroke-width: 2; }
.spell { stroke: var(--series-1); stroke-width: 2; stroke-linecap: round; }
.spell + .dot, circle.dot:not(.c1):not(.c2) { fill: var(--series-1); }
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
.rule { width: 16px; height: 2px; border-radius: 1px; display: inline-block; }
.rule.c1 { background: var(--series-1); }
.rule.c2 { background: var(--series-2); }
.rule.dash { background: none; height: 0;
             border-top: 2px dashed var(--text-secondary); }
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
  /* A print-out has no tabs to click, so it carries every panel. */
  .tabs > div[class^="panel-"] { display: block !important; }
  .tab-strip { display: none; }
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


def tabs(panels: list[tuple[str, str, str]]) -> str:
    """A tab strip built out of radio buttons, so it needs no script.

    The page's only JavaScript is the hover readout, and everything it
    shows is also in a table; switching tabs is navigation, which is a
    worse thing to lose. A radio input and a sibling selector do it in
    CSS, keep keyboard focus and arrow keys for free, and leave the
    page working in a print-out, in a text browser, and with scripting
    switched off -- where every panel simply shows at once.

    Panels with nothing in them are left out rather than rendered as
    an empty tab a reader can click into and find nothing.
    """
    filled = [(key, label, html) for key, label, html in panels if html]
    if len(filled) < 2:
        return "".join(html for _, _, html in filled)

    inputs, strip, blocks = [], [], []
    for index, (key, label, html) in enumerate(filled):
        inputs.append(
            f'<input class="tab-radio" type="radio" name="view" '
            f'id="tab-{key}"{" checked" if not index else ""}>')
        strip.append(f'<label class="tab" for="tab-{key}">{_e(label)}</label>')
        blocks.append(f'<div class="panel-{key}">{html}</div>')
    return (f'<div class="tabs">{"".join(inputs)}'
            f'<nav class="tab-strip">{"".join(strip)}</nav>'
            f'{"".join(blocks)}</div>')


def build(session: Session, *, reveal: bool = False,
          generated: datetime | None = None) -> str:
    """The whole page, as one string."""
    page = Page(
        held={p: own(session, p) for p in PLATFORMS},
        generated=local(generated or clock_now()),
        reveal=reveal,
    )
    stamp = page.generated.strftime("%Y-%m-%d %H:%M") if page.generated else "—"
    overview = "".join([
        _douyin(session, page),
        _daily(session, page),
        _comebacks(page),
        _context(page),
    ])
    analysis = _content(session, page)
    body = "".join([
        "<header><h1>Takedown observatory</h1>",
        '<p class="sub">Chinese-language WLW posts, watched daily for '
        f"removal. Read out of the collection at {_e(stamp)}.</p></header>",
        tabs([
            ("overview", "Overview 总览", overview),
            ("analysis", "抖音内容分析 (Douyin content)", analysis),
        ]),
        _method(),
    ])
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Takedown observatory</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<main>{body}</main>"
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
