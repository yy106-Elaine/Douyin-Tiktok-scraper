"""What the collection says so far, in the terms it can support.

    ./.venv/bin/python -m app.analyse
    ./.venv/bin/python -m app.analyse --csv findings.csv

Four tables and an export. The tables are the ones that can be read
off today's data without assuming anything it does not contain; the
export is for the survival analysis proper, which belongs in R or
lifelines and not here.

The arithmetic is deliberately plain. What is not plain, and what this
module mostly exists to enforce, is *which* comparisons the data
supports:

 -- A raw removal rate is not comparable across platforms. Douyin is
    searched by tag the day of posting; TikTok is searched by an
    English phrase and returns videos already weeks old, which is a
    survivor set: the ones pulled on day one never appear in it. So
    the cross-platform table reports collection age beside the rate,
    and the comparable number is the horizon below.

 -- A median time to removal needs half the population to have been
    removed. At a fifth, the median is not "long", it is undefined,
    and a number computed anyway is an artefact. So this reports
    survival at fixed horizons instead, and says how many events
    there are.

 -- A removal time is an interval, never an instant: gone by this
    check, alive at the last one. The width of that interval is the
    checking cadence, and it is printed beside every rate so nothing
    is ever quoted more precisely than the schedule allows.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import local, local_date
from .links import describe
from .platforms import PLATFORM_FAMILY, filter_policy
from .relevance import classify
from . import labels
from .models import LinkCheck, SharedLink, WebVideo
from .survival import (
    Finding,
    age_at_collection,
    by_collection_age,
    findings,
    horizon,
    summarise,
)

#: The questions the horizon table asks. Short ones first: removals
#: cluster early, and a day is the resolution the daily pass supports.
HORIZONS: tuple[timedelta, ...] = (
    timedelta(days=1),
    timedelta(days=3),
    timedelta(days=7),
)

PLATFORMS: tuple[str, ...] = ("douyin", "douyin_note", "tiktok", "youtube")


def own(session: Session, platform: str) -> list[Finding]:
    """This platform's findings, not its family's.

    `findings` groups 图文 under douyin, which is what the dashboard
    wants and the opposite of what a comparison between the two wants.
    """
    return [f for f in findings(session, platform) if f.platform == platform]


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _days(span: timedelta | None) -> str:
    if span is None:
        return "—"
    hours = span.total_seconds() / 3600
    return f"{hours / 24:.1f}d" if hours >= 24 else f"{hours:.0f}h"


def observed_days(session: Session, platform: str) -> dict[str, set[str]]:
    """Which videos this platform saw a check on, per local day.

    Built from the checks themselves rather than from a calendar, so a
    day the study did not run is an empty set and says so, instead of
    contributing a zero to a hazard series. 2026-09-27 is such a day.
    """
    seen: dict[str, set[str]] = {}
    for check in session.scalars(
        select(LinkCheck).where(
            LinkCheck.platform == platform, LinkCheck.target_kind == "video"
        )
    ):
        if check.video_id and check.checked_at:
            seen.setdefault(local_date(check.checked_at).isoformat(), set()).add(
                check.video_id
            )
    return seen


def daily_hazard(
    session: Session, platform: str, items: list[Finding]
) -> list[tuple[str, int, int, float | None]]:
    """(day, at risk, newly gone, hazard) for each day that was observed.

    At risk means: checked that day, and not already known to be gone
    before it. A day with no checks at all does not appear -- it is
    missing, not zero, and the difference is the whole reason the
    series is built from observations rather than from dates.
    """
    gone_on: dict[str, set[str]] = {}
    for finding in items:
        if finding.first_gone_ever:
            gone_on.setdefault(
                local_date(finding.first_gone_ever).isoformat(), set()
            ).add(finding.video_id)

    seen = observed_days(session, platform)
    out = []
    already: set[str] = set()
    for day in sorted(seen):
        checked = seen[day]
        at_risk = checked - already
        events = gone_on.get(day, set()) & checked
        rate = len(events) / len(at_risk) if at_risk else None
        out.append((day, len(at_risk), len(events), rate))
        already |= events
    return out


def _capture_table(platform: str):
    """The table the phone writes into for this platform, if any."""
    from .parsers import PLATFORM_TABLES

    registered = PLATFORM_TABLES.get(PLATFORM_FAMILY.get(platform, platform))
    return registered[0] if registered else None


def captions(session: Session, platform: str) -> dict[str, str]:
    """The caption per video, the capture first and the fetch second.

    **The order matters and is not a preference.** When a Douyin
    request comes back carrying a different video's record, the post
    is gone, and `fetch_videos.wipe` empties the fetched row --
    correctly, since nothing in it belonged to that id any more. The
    caption goes with it. So reading captions off the fetched rows
    alone returns captions for the posts that survived and blanks for
    the posts that were removed: a corpus of survivors, and the exact
    bias that would make "content predicts removal" unanswerable.

    The capture the phone made is the caption as it stood on screen
    when the post was collected. It is never wiped, it is what the
    post actually said, and for a removed post it is the only copy
    left. It is read first for every video, and the fetched row only
    fills in the ids the phone never saw.
    """
    said: dict[str, str] = {}
    model = _capture_table(platform)
    if model is not None:
        for video_id, caption in session.execute(
            select(model.video_id, model.caption).where(
                model.video_id.isnot(None), model.caption.isnot(None)
            )
        ):
            said.setdefault(video_id, caption or "")

    for row in session.scalars(
        select(WebVideo).where(WebVideo.platform == platform)
    ):
        if row.video_id:
            said.setdefault(row.video_id, (row.caption or "").replace("\n", " "))
    # A pasted share blob carries its own caption, and nothing else
    # was reading it. Until `app.daily` fetches the page there is no
    # fetched row, so every hand-pasted post counted as having no
    # caption at all -- and if the post is removed before that first
    # fetch ever happens, the blob is the only copy of its text there
    # will ever be. Truncated by the share sheet, and an ellipsis is
    # more than an empty column.
    for link in session.scalars(
        select(SharedLink).where(SharedLink.platform == platform)
    ):
        if not link.video_id:
            continue
        held = said.get(link.video_id)
        if held:
            continue
        said[link.video_id] = (describe(link.raw_text or "").caption or "")
    return said


def excluded(session: Session, platform: str) -> set[str]:
    """Videos the topic filter marked out of scope, by video id.

    Marked, never deleted -- see `relevance` -- so they are still in
    the tables and still turn up in a caption dump unless something
    takes them out. A classification scheme designed over a sample
    that includes cookery videos and a shooter-game stream is a
    scheme with categories for cookery and shooter games.
    """
    model = _capture_table(platform)
    if model is None:
        return set()
    return {
        video_id
        for video_id, in session.execute(
            select(model.video_id).where(
                model.video_id.isnot(None), model.relevance.isnot(None)
            )
        )
    }


def caption_dump(session: Session, path: str) -> int:
    """Every distinct in-scope Douyin caption, one per line, nothing else.

    For designing a classification scheme against the corpus that
    exists rather than the one imagined. Deliberately carries no id,
    no handle, no date and -- above all -- no outcome: a taxonomy
    built while looking at which posts were removed is a taxonomy
    fitted to the answer, and every later claim that content predicts
    removal would be circular.

    Rows the topic filter excluded are left out. They are still in the
    database, as they must be, but a cookery video in the sample
    produces a category for cookery.
    """
    seen: set[str] = set()
    empty = 0
    for platform in ("douyin", "douyin_note"):
        out_of_scope = excluded(session, platform)
        for video_id, text in captions(session, platform).items():
            if video_id in out_of_scope:
                continue
            # A hand-pasted link has no capture row, so `relevance`
            # never saw it and `excluded` cannot know about it. That
            # is how a restaurant review and a shooter-game stream
            # were still in the sample after the first fix. The text
            # is here, so classify it here.
            if text and classify(text, policy=filter_policy(platform)):
                continue
            cleaned = " ".join(text.split())
            if not cleaned:
                empty += 1
                continue
            seen.add(cleaned)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"# {len(seen)} distinct captions; "
                     f"{empty} post(s) carry none\n")
        for line in sorted(seen):
            handle.write(line + "\n")
    return len(seen)


def douyin_format(session: Session) -> dict[str, str]:
    """Which Douyin format each video id is: a video, or a 图文.

    The capture tables do not record it -- a post the phone read is a
    row in `douyin_posts` whichever format it was. What knows is
    everything written after the link was resolved: the fetched page,
    the shared link and every check all carry the platform the study
    tracks it under. `douyin_note` wins any disagreement, because that
    label is only ever written by a resolver that saw a `/note/` URL,
    while `douyin` is also the default.
    """
    found: dict[str, str] = {}
    for model in (WebVideo, SharedLink, LinkCheck):
        for video_id, platform in session.execute(
            select(model.video_id, model.platform).where(
                model.video_id.isnot(None),
                model.platform.in_(("douyin", "douyin_note")),
            )
        ):
            if platform == "douyin_note" or video_id not in found:
                found[video_id] = platform
    return found


def corpus_captions(session: Session) -> list[tuple[str, str, str]]:
    """(platform, video_id, caption) for every in-scope Douyin post, once.

    One definition of "the corpus", used by the label export and by
    the page, so the two can never disagree about what was counted.

    **Keyed by video id, because the two Douyin formats share one
    capture table.** `captions("douyin")` and `captions("douyin_note")`
    both read `douyin_posts` -- the phone writes there whichever
    format it read -- so walking the two platforms and appending
    returned every captured post twice, and the page reported a
    corpus half again larger than the one the dashboard counts.

    Two exclusions, for two different reasons: the topic filter's own
    mark, and -- for a hand-pasted link, which has no capture row for
    `relevance` to have marked -- the filter run over the text here.
    """
    kind = douyin_format(session)
    out_of_scope = excluded(session, "douyin") | excluded(session, "douyin_note")
    # A link copied by hand is never excluded on its text. The same
    # carve-out `views.py` makes, and for the same reason: the share
    # blob truncates the caption, usually right where the tags are,
    # so the text is no evidence about the post. These were found by
    # searching a community tag, so by construction they carry one --
    # excluding them because the copy was cut short would drop the
    # rows that cost the most to collect.
    by_hand = {
        video_id
        for video_id, in session.execute(
            select(SharedLink.video_id).where(
                SharedLink.video_id.isnot(None),
                SharedLink.source == "pasted",
            )
        )
    }

    merged: dict[str, str] = {}
    for platform in ("douyin", "douyin_note"):
        for video_id, text in captions(session, platform).items():
            flat = " ".join(text.split())
            if flat or video_id not in merged:
                merged.setdefault(video_id, flat)

    found: list[tuple[str, str, str]] = []
    for video_id, flat in sorted(merged.items()):
        if video_id in out_of_scope:
            continue
        platform = kind.get(video_id, "douyin")
        if (
            flat
            and video_id not in by_hand
            and not labels.truncated(flat)
            and classify(flat, policy=filter_policy(platform))
        ):
            continue
        found.append((platform, video_id, flat))
    return found


def author_names(session: Session) -> dict[str, str]:
    """The display name beside each Douyin video id.

    Read from the capture first and the fetched page second, for the
    same reason captions are: a removed post's fetched row is wiped,
    and the name the author was using is part of what was lost.
    """
    found: dict[str, str] = {}
    model = _capture_table("douyin")
    if model is not None:
        for video_id, name in session.execute(
            select(model.video_id, model.author_name).where(
                model.video_id.isnot(None), model.author_name.isnot(None)
            )
        ):
            found.setdefault(video_id, name)
    for video_id, name in session.execute(
        select(WebVideo.video_id, WebVideo.author_name).where(
            WebVideo.video_id.isnot(None), WebVideo.author_name.isnot(None)
        )
    ):
        found.setdefault(video_id, name)
    # And the share blob, for the same reason the caption is read from
    # it: a hand-pasted post has no other record of who posted it
    # until the page is fetched.
    for link in session.scalars(
        select(SharedLink).where(SharedLink.video_id.isnot(None))
    ):
        name = describe(link.raw_text or "").author_name
        if name:
            found.setdefault(link.video_id, name)
    return found


def label_dump(session: Session, path: str) -> int:
    """One row per in-scope Douyin post, with the tag columns filled in.

    The tag axes are matched, not judged (see `app/labels.py`), so
    they are written here rather than sent to a model: exactly
    reproducible, free, and needing no agreement statistic. Only the
    content category is left empty, because that one needs a reader.

    Unlike `caption_dump`, this one carries the outcome. Designing a
    scheme while looking at the answer is circular; *analysing* with
    the answer present is the entire point, and these two files exist
    separately so that the first cannot quietly become the second.
    """
    from .survival import Finding

    verdicts: dict[str, Finding] = {
        f.video_id: f for p in ("douyin", "douyin_note") for f in own(session, p)
    }
    written = 0
    with open(path, "w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow([
            "platform", "video_id", "caption", "truncated",
            "wlw_tags", "tph_tags", "tph_terms", "compliance",
            "account_marks", "content", "is_gone", "first_gone_at",
            "collected_at",
        ])
        named = author_names(session)
        for platform, video_id, flat in corpus_captions(session):
                found = verdicts.get(video_id)
                out.writerow([
                    platform, video_id, flat,
                    int(labels.truncated(flat)),
                    "|".join(labels.wlw_tags(flat)) if flat else "",
                    "|".join(labels.tph_tags(flat)) if flat else "",
                    "|".join(labels.tph_terms(flat)),
                    int(labels.compliance(flat)),
                    "|".join(labels.account_marks(named.get(video_id))),
                    "",  # for the content category, once it is coded
                    int(bool(found and found.is_gone)) if found else "",
                    local(found.first_gone_ever) if found else "",
                    local(found.collected_at) if found else "",
                ])
                written += 1
    return written


def export(session: Session, path: str) -> int:
    """One row per video, for a survival analysis done properly elsewhere.

    Times are the researcher's local wall clock, because that is what
    every other output here shows and a CSV that disagrees with the
    dashboard by four hours is a trap. The interval columns are what
    an interval-censored fit needs: last seen alive, first seen gone.
    """
    written = 0
    with open(path, "w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow([
            "platform", "video_id", "author_handle", "url",
            "published_at", "collected_at", "age_at_collection_hours",
            "first_checked_at", "last_alive_at", "first_gone_at",
            "came_back_at", "disappearances", "checks", "uninformative",
            "current", "outcome", "is_gone", "caption",
        ])
        for platform in PLATFORMS:
            said = captions(session, platform)
            for f in own(session, platform):
                age = age_at_collection(f)
                out.writerow([
                    f.platform, f.video_id, f.author_handle or "", f.url or "",
                    local(f.published_at) or "", local(f.collected_at) or "",
                    f"{age.total_seconds() / 3600:.1f}" if age else "",
                    local(f.first_checked_at) or "", local(f.last_alive_at) or "",
                    local(f.first_gone_ever) or "", local(f.came_back_at) or "",
                    f.disappearances, f.checks, f.uninformative,
                    f.current or "", f.outcome or "", int(bool(f.is_gone)),
                    said.get(f.video_id, "")[:500],
                ])
                written += 1
    return written


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", help="also write one row per video here")
    parser.add_argument(
        "--labels",
        help="also write one row per in-scope Douyin post with the tag "
             "columns filled in and the content column left for coding",
    )
    parser.add_argument(
        "--captions",
        help="also write every distinct Douyin caption here, one per line, "
             "with no ids and no removal outcomes",
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        held = {p: own(session, p) for p in PLATFORMS}

        print("\n=== What was tracked, and what happened to it ===\n")
        print(f"{'platform':13} {'tracked':>8} {'gone':>6} {'alive':>6} "
              f"{'no info':>8} {'rate':>7} {'± window':>9}")
        for platform, items in held.items():
            s = summarise(items)
            print(f"{platform:13} {s.tracked:8} {s.gone:6} {s.alive:6} "
                  f"{s.unmeasured:8} {_pct(s.rate):>7} "
                  f"{_days(s.median_uncertainty):>9}")
        print("\n  rate = gone / (gone + alive). Videos never read are out of the\n"
              "  denominator, not assumed alive. ± window is the median width of\n"
              "  the removal intervals: no lifetime is known better than this.")

        print("\n=== How old each video was when we started watching ===\n")
        print("  A rate is only comparable within a band. A search that returns\n"
              "  month-old videos returns the ones that lasted a month.\n")
        for platform, items in held.items():
            bands = by_collection_age(items)
            if not bands:
                continue
            print(f"  {platform}")
            for label, s in bands:
                print(f"    {label:22} {s.tracked:5} tracked  "
                      f"{s.gone:4} gone  {_pct(s.rate):>7}")
            print()

        print("=== Removed within T of publication, among videos watched that early ===\n")
        print(f"{'platform':13} {'horizon':>8} {'eligible':>9} {'removed':>8} "
              f"{'survived':>9} {'too early':>10} {'rate':>7}")
        for platform, items in held.items():
            for age in HORIZONS:
                h = horizon(items, age)
                if not h.eligible:
                    continue
                print(f"{platform:13} {_days(age):>8} {h.eligible:9} {h.removed:8} "
                      f"{h.survived:9} {h.censored:10} {_pct(h.rate):>7}")
        print("\n  'eligible' excludes videos first seen after T -- nothing was\n"
              "  watching them that early, so for them the question has no answer.\n"
              "  'too early' is still alive but not yet old enough to say.\n"
              "  This is the number that compares across platforms; the raw rate\n"
              "  above is not.")

        print("\n=== New removals per day observed ===\n")
        for platform, items in held.items():
            rows = daily_hazard(session, platform, items)
            if not rows:
                continue
            print(f"  {platform}")
            for day, at_risk, events, rate in rows:
                bar = "#" * min(events, 40)
                print(f"    {day}  at risk {at_risk:4}  gone {events:3}  "
                      f"{_pct(rate):>6}  {bar}")
            print()
        print("  Days the study did not run are absent, never zero. A hazard of\n"
              "  zero means it looked and found nothing; a missing day means it\n"
              "  did not look, and the removals of that day are dated to the next\n"
              "  one it did.")

        back = [
            (p, f) for p, items in held.items() for f in items if f.came_back_at
        ]
        if back:
            print("\n=== Came back ===\n")
            for platform, f in sorted(back, key=lambda pair: pair[1].came_back_at):
                print(f"  {platform:12} {f.video_id}")
                print(f"     gone by {local(f.first_gone_ever)}  "
                      f"back by {local(f.came_back_at)}")
            print("\n  Those are the times the instrument looked, not the times\n"
                  "  anything happened. The data supports an interval, never a\n"
                  "  duration. With this many events it is a description, not a\n"
                  "  rate.")

        if args.csv:
            written = export(session, args.csv)
            print(f"\n{written} row(s) written to {args.csv}")

        if args.captions:
            written = caption_dump(session, args.captions)
            print(f"{written} distinct caption(s) written to {args.captions}")

        if args.labels:
            written = label_dump(session, args.labels)
            print(f"{written} labelled row(s) written to {args.labels}")


if __name__ == "__main__":  # pragma: no cover
    main()
