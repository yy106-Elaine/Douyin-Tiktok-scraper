"""One place that turns a stored instant into a shown one.

Everything is stored in UTC, which is right: an instant is an instant,
and a database that mixes zones cannot be compared with itself. But
nobody reads UTC. A collection run at 22:52 in Boston is 02:52 the
next day in UTC, so the per-day chart put an evening's work under
tomorrow and left today reading zero -- and "why did today collect
nothing" is exactly the question the chart exists to answer.

So the boundary is here: UTC below, the researcher's own day above.
Only display and day-bucketing convert; nothing stored ever does.

The zone is configurable because the researcher's day is the one that
matters, and this study is run from Eastern time.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .config import settings


def zone() -> ZoneInfo:
    return ZoneInfo(settings.display_timezone)


def local(moment: datetime | None) -> datetime | None:
    """A stored UTC instant as a wall clock in the display zone.

    Naive datetimes are read as UTC, which is what every column in
    this database holds. The result is naive too, so callers can
    format it without every template learning about offsets.
    """
    if moment is None:
        return None
    aware = moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment
    return aware.astimezone(zone()).replace(tzinfo=None)


def local_date(moment: datetime | None) -> date | None:
    """The day a moment fell on, for someone in the display zone."""
    shown = local(moment)
    return None if shown is None else shown.date()


def now() -> datetime:
    """Now, as a naive UTC instant -- what the columns hold."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today() -> date:
    """Today, in the display zone."""
    return local_date(now())


def start_of_local_day(day: date) -> datetime:
    """Midnight of a local day, as the naive UTC instant it is.

    Bucketing has to compare stored instants, so a local day boundary
    has to come back as UTC to be usable in a query or a comparison.
    """
    midnight = datetime.combine(day, datetime.min.time(), tzinfo=zone())
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)
