"""Offline reverse geocoding (nearest populated place). Data: GeoNames cities1000, CC BY 4.0.

The dataset is loaded lazily on first use and indexed in 1x1 degree buckets.
"""

from __future__ import annotations

import gzip
import math
import threading
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

MAX_DISTANCE_KM = 50.0
_EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    admin1: str
    country: str
    distance_km: float


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


_Row = tuple[float, float, str, str, str]


class Geocoder:
    def __init__(self, data_path: Path | None = None) -> None:
        self._data_path = data_path
        self._buckets: dict[tuple[int, int], list[_Row]] | None = None
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
                    dist = _haversine_km(lat, lon, row[0], row[1])
                    if best is None or dist < best[0]:
                        best = (dist, row)
        if best is None or best[0] > MAX_DISTANCE_KM:
            return None
        dist, (_, _, name, admin1, country) = best
        return Place(name=name, admin1=admin1, country=country, distance_km=round(dist, 2))
