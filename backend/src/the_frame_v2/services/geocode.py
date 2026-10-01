"""Offline geocoding over GeoNames cities1000 (CC BY 4.0): the nearest populated place to a
position (`reverse`, at ingest) and places by name (`search`, the `place near` filter's picker).

The dataset is loaded lazily on first use: indexed in 1x1 degree buckets for `reverse`, and as a
sorted list of folded names for `search` (built on the first search only).
"""

from __future__ import annotations

import gzip
import math
import threading
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from the_frame_v2.domain.geo import haversine_km

MAX_DISTANCE_KM = 50.0
SEARCH_SCAN = 2000
"""Prefix matches looked at per search before ranking — a one-letter query matches thousands."""


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    admin1: str
    country: str
    distance_km: float


@dataclass(frozen=True, slots=True)
class NamedPlace:
    """A place of the dataset, with its position: what the `place near` picker offers."""

    name: str
    admin1: str
    country: str
    lat: float
    lon: float


def fold(text: str) -> str:
    """Text as a search compares it: no accents, no case, hyphens and apostrophes as spaces.

    "São Paulo", "sao paulo" and "SAO-PAULO" are one key; so are "Kyōto" and "kyoto".
    """
    decomposed = unicodedata.normalize("NFKD", text)
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Hyphen, apostrophes, right single quote, okina (Hawaiian and Tongan names).
    for mark in "-'`\u2019\u02bb":
        bare = bare.replace(mark, " ")
    return " ".join(bare.casefold().split())


_Row = tuple[float, float, str, str, str]


class Geocoder:
    def __init__(self, data_path: Path | None = None) -> None:
        self._data_path = data_path
        self._buckets: dict[tuple[int, int], list[_Row]] | None = None
        self._names: tuple[list[str], list[_Row]] | None = None
        self._lock = threading.Lock()

    def _load(self) -> dict[tuple[int, int], list[_Row]]:
        with self._lock:
            if self._buckets is not None:
                return self._buckets
            buckets: dict[tuple[int, int], list[_Row]] = {}
            if self._data_path is not None:
                raw = self._data_path.read_bytes()
            else:
                ref = resources.files("the_frame_v2") / "assets/geonames/cities1000.tsv.gz"
                raw = ref.read_bytes()
            for line in gzip.decompress(raw).decode("utf-8").splitlines():
                name, lat_s, lon_s, admin1, country = line.split("\t")
                lat, lon = float(lat_s), float(lon_s)
                buckets.setdefault((math.floor(lat), math.floor(lon)), []).append(
                    (lat, lon, name, admin1, country)
                )
            self._buckets = buckets
            return buckets

    def reverse(self, lat: float, lon: float) -> Place | None:
        buckets = self._load()
        best: tuple[float, _Row] | None = None
        base_lat, base_lon = math.floor(lat), math.floor(lon)
        # 50 km < 1° of latitude; longitude degrees shrink towards the poles, widen the search.
        lon_span = 1 if abs(lat) < 60 else 3 if abs(lat) < 80 else 180
        for dlat in (-1, 0, 1):
            for dlon in range(-lon_span, lon_span + 1):
                key = (base_lat + dlat, ((base_lon + dlon + 180) % 360) - 180)
                for row in buckets.get(key, ()):
                    dist = haversine_km(lat, lon, row[0], row[1])
                    if best is None or dist < best[0]:
                        best = (dist, row)
        if best is None or best[0] > MAX_DISTANCE_KM:
            return None
        dist, (_, _, name, admin1, country) = best
        return Place(name=name, admin1=admin1, country=country, distance_km=round(dist, 2))

    def _name_index(self) -> tuple[list[str], list[_Row]]:
        """Every place under its folded name, sorted — a prefix is one `bisect` away."""
        buckets = self._load()
        with self._lock:
            if self._names is None:
                pairs = sorted(
                    ((fold(row[2]), row) for rows in buckets.values() for row in rows),
                    key=lambda pair: pair[0],
                )
                self._names = ([key for key, _ in pairs], [row for _, row in pairs])
            return self._names

    def search(self, query: str, limit: int = 20) -> list[NamedPlace]:
        """Places whose name starts with `query`, accents and case ignored.

        `"paris, tex"`: what follows a comma narrows by region or country (each part a prefix of
        either), for the names the world reuses. Exact names come first, then shorter ones — the
        dataset has no population to rank by, so the caller may rank further (the library does).
        """
        head, *rest = [fold(part) for part in query.split(",")]
        qualifiers = [part for part in rest if part]
        if not head:
            return []
        keys, rows = self._name_index()
        found: list[tuple[str, _Row]] = []
        index = bisect_left(keys, head)
        while index < len(keys) and keys[index].startswith(head) and len(found) < SEARCH_SCAN:
            row = rows[index]
            if all(fold(row[3]).startswith(q) or fold(row[4]).startswith(q) for q in qualifiers):
                found.append((keys[index], row))
            index += 1
        found.sort(key=lambda pair: (pair[0] != head, len(pair[0]), pair[0], pair[1][4]))
        return [
            NamedPlace(name=row[2], admin1=row[3], country=row[4], lat=row[0], lon=row[1])
            for _, row in found[:limit]
        ]
