"""Places: a read-only view of where the library's photos were taken (docs/organization.md §1).

A place is photo **metadata** — the offline reverse geocoder fills `place_name`, `place_admin1`
and `place_country` from the GPS position at ingest — so it is never a tag: nothing to type, and
nothing to keep in sync. This module only counts, per country → region → place, the live photos
taken there and the live artworks using at least one of them (an artwork is "from Kyoto" when one
of its photos is, the reading of the `place` filter clause).

A photo without a position (Android's photo picker strips GPS) has no place: it is counted apart.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from the_frame_v2.db.models import Artwork, ArtworkPhoto, Photo


@dataclass(slots=True)
class Place:
    name: str
    photo_count: int = 0
    artwork_count: int = 0
    children: list[Place] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Places:
    countries: list[Place]
    unplaced_photos: int


def _key(value: str | None) -> str:
    return value or ""


def places(session: Session) -> Places:
    """Country → region → place, each with its photo and artwork counts, most photos first.

    Counts are taken per level (not summed from the level below) so an artwork made of photos
    from two cities of one country counts once for that country.
    """
    live = Photo.deleted_at.is_(None)
    levels = (
        (Photo.place_country,),
        (Photo.place_country, Photo.place_admin1),
        (Photo.place_country, Photo.place_admin1, Photo.place_name),
    )
    photo_counts: list[dict[tuple[str, ...], int]] = []
    artwork_counts: list[dict[tuple[str, ...], int]] = []
    for columns in levels:
        photo_counts.append(
            {
                tuple(_key(v) for v in row[:-1]): int(row[-1])
                for row in session.execute(
                    select(*columns, func.count(Photo.id))
                    .where(live, Photo.place_country.is_not(None))
                    .group_by(*columns)
                )
            }
        )
        artwork_counts.append(
            {
                tuple(_key(v) for v in row[:-1]): int(row[-1])
                for row in session.execute(
                    select(*columns, func.count(distinct(Artwork.id)))
                    .join(ArtworkPhoto, ArtworkPhoto.photo_id == Photo.id)
                    .join(Artwork, Artwork.id == ArtworkPhoto.artwork_id)
                    .where(live, Photo.place_country.is_not(None), Artwork.deleted_at.is_(None))
                    .group_by(*columns)
                )
            }
        )

    def node(depth: int, key: tuple[str, ...]) -> Place:
        return Place(
            name=key[-1],
            photo_count=photo_counts[depth].get(key, 0),
            artwork_count=artwork_counts[depth].get(key, 0),
        )

    children: dict[tuple[str, ...], list[tuple[str, ...]]] = defaultdict(list)
    for depth in (1, 2):
        for key in photo_counts[depth]:
            children[key[:-1]].append(key)

    def build(depth: int, key: tuple[str, ...]) -> Place:
        place = node(depth, key)
        if depth < 2:
            place.children = [build(depth + 1, child) for child in children.get(key, [])]
            place.children.sort(key=lambda p: (-p.photo_count, p.name.lower()))
        return place

    countries = [build(0, key) for key in photo_counts[0]]
    countries.sort(key=lambda p: (-p.photo_count, p.name.lower()))
    unplaced = int(
        session.scalar(select(func.count(Photo.id)).where(live, Photo.place_country.is_(None))) or 0
    )
    return Places(countries, unplaced)
