"""Places: a read-only view of where the library's photos were taken (docs/organization.md §1).

A place is photo **metadata** — the offline reverse geocoder fills `place_name`, `place_admin1`
and `place_country` from the GPS position at ingest — so it is never a tag: nothing to type, and
nothing to keep in sync. This module only counts, per country → region → place, the live photos
taken there and the live artworks using at least one of them (an artwork is "from Kyoto" when one
of its photos is, the reading of the `place` filter clause).

A photo without a position (Android's photo picker strips GPS) has no place: it is counted apart,
and so are the artworks none of whose photos has one — the `place near` filter can never match them.

`search` is the `place near` picker: places of the offline dataset by name, the library's own first.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from frame_it.db.models import Artwork, ArtworkPhoto, Photo
from frame_it.services.geocode import Geocoder


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
    unlocated_artworks: int
    """Live artworks none of whose live photos has a GPS position."""


@dataclass(frozen=True, slots=True)
class PlaceMatch:
    """A place of the offline dataset, and how many live photos the library has there."""

    name: str
    admin1: str
    country: str
    lat: float
    lon: float
    photo_count: int


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
    return Places(countries, unplaced, unlocated_artworks(session))


def unlocated_artworks(session: Session) -> int:
    """Live artworks with no live photo carrying a GPS position — out of reach of `place near`."""
    located = (
        select(ArtworkPhoto.artwork_id)
        .join(Photo, Photo.id == ArtworkPhoto.photo_id)
        .where(Photo.deleted_at.is_(None), Photo.gps_lat.is_not(None), Photo.gps_lon.is_not(None))
    )
    return int(
        session.scalar(
            select(func.count(Artwork.id)).where(
                Artwork.deleted_at.is_(None), Artwork.id.not_in(located)
            )
        )
        or 0
    )


SEARCH_CANDIDATES = 200


def search(session: Session, geocoder: Geocoder, query: str, limit: int = 8) -> list[PlaceMatch]:
    """Places named like `query`, the ones the library knows first.

    The dataset has no population, so "Paris" alone is a tie between a dozen places. The library
    breaks it: places where it has photos come first, then places in countries where it has
    photos, then the geocoder's own order (exact names, then shorter ones).
    """
    candidates = geocoder.search(query, limit=SEARCH_CANDIDATES)
    if not candidates:
        return []
    live = Photo.deleted_at.is_(None)
    at_place = {
        (row[0], _key(row[1]), _key(row[2])): int(row[3])
        for row in session.execute(
            select(Photo.place_name, Photo.place_admin1, Photo.place_country, func.count(Photo.id))
            .where(live, Photo.place_name.in_({c.name for c in candidates}))
            .group_by(Photo.place_name, Photo.place_admin1, Photo.place_country)
        )
    }
    in_country = {
        _key(row[0]): int(row[1])
        for row in session.execute(
            select(Photo.place_country, func.count(Photo.id))
            .where(live, Photo.place_country.is_not(None))
            .group_by(Photo.place_country)
        )
    }
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (
            -at_place.get((item[1].name, item[1].admin1, item[1].country), 0),
            -in_country.get(item[1].country, 0),
            item[0],
        ),
    )
    return [
        PlaceMatch(
            name=place.name,
            admin1=place.admin1,
            country=place.country,
            lat=place.lat,
            lon=place.lon,
            photo_count=at_place.get((place.name, place.admin1, place.country), 0),
        )
        for _, place in ranked[:limit]
    ]
