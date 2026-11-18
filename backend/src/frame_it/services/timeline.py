"""Timeline: a read-only view of when the library's photos were taken (docs/organization.md §1).

The twin of the Places view over the capture time: per year → month, the live photos taken then
and the live artworks using at least one of them (an artwork is "from March 2024" when one of its
photos is — the reading of the `taken_at` filter clause, which the view links to).

`taken_at` is floating camera-local time stored as a sortable ISO string (invariant 9), so a
period is a prefix of it and is never timezone-converted. A photo without a capture time (no EXIF
date: screenshots, exports, edited copies) has no place on the timeline: it is counted apart.

`taken_in` is the same period as a photo condition — the photo grid's `?taken=` filter.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

from sqlalchemy import ColumnElement, String, distinct, false, func, select
from sqlalchemy.orm import Session

from frame_it.db.models import Artwork, ArtworkPhoto, Photo

PERIOD_PATTERN = r"^[0-9]{4}(-(0[1-9]|1[0-2]))?$"
"""A year (`2024`) or a month (`2024-03`)."""


@dataclass(slots=True)
class Month:
    month: int
    """1 = January."""
    photo_count: int = 0
    artwork_count: int = 0


@dataclass(slots=True)
class Year:
    year: int
    photo_count: int = 0
    artwork_count: int = 0
    months: list[Month] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Timeline:
    years: list[Year]
    undated_photos: int


def timeline(session: Session) -> Timeline:
    """Years → months, each with its photo and artwork counts, the most recent first.

    Counts are taken per level (not summed from the months) so an artwork made of photos from two
    months counts once for the year.
    """
    live = Photo.deleted_at.is_(None)
    dated = Photo.taken_at.is_not(None)
    photo_counts: list[dict[str, int]] = []
    artwork_counts: list[dict[str, int]] = []
    for length in (4, 7):  # `YYYY`, `YYYY-MM`
        period = func.substr(Photo.taken_at, 1, length, type_=String())
        photo_counts.append(
            {
                str(key): int(count)
                for key, count in session.execute(
                    select(period, func.count(Photo.id)).where(live, dated).group_by(period)
                )
            }
        )
        artwork_counts.append(
            {
                str(key): int(count)
                for key, count in session.execute(
                    select(period, func.count(distinct(Artwork.id)))
                    .join(ArtworkPhoto, ArtworkPhoto.photo_id == Photo.id)
                    .join(Artwork, Artwork.id == ArtworkPhoto.artwork_id)
                    .where(live, dated, Artwork.deleted_at.is_(None))
                    .group_by(period)
                )
            }
        )

    years = {
        key: Year(int(key), count, artwork_counts[0].get(key, 0))
        for key, count in photo_counts[0].items()
    }
    for key, count in photo_counts[1].items():
        year = years.get(key[:4])
        if year is not None:
            year.months.append(Month(int(key[5:7]), count, artwork_counts[1].get(key, 0)))
    for year in years.values():
        year.months.sort(key=lambda m: -m.month)
    undated = int(
        session.scalar(select(func.count(Photo.id)).where(live, Photo.taken_at.is_(None))) or 0
    )
    return Timeline(sorted(years.values(), key=lambda y: -y.year), undated)


def taken_in(period: str) -> ColumnElement[bool]:
    """A photo taken during `period` (`PERIOD_PATTERN`, already checked), first to last moment."""
    year = int(period[:4])
    if year < 1:
        return false()
    if len(period) == 4:
        first, last = date(year, 1, 1), date(year, 12, 31)
    else:
        month = int(period[5:7])
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
    return Photo.taken_at.between(
        datetime.combine(first, time.min, tzinfo=UTC), datetime.combine(last, time.max, tzinfo=UTC)
    )
