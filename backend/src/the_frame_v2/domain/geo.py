"""Distances on the globe — pure, shared by the offline geocoder and the `place near` filter.

A great-circle distance (haversine) on a spherical Earth: well within a few metres of the
ellipsoid at the scales this app cares about (a city, a region), and cheap enough to run per row.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEGREE = EARTH_RADIUS_KM * math.pi / 180
"""Length of one degree of latitude (and of longitude at the equator)."""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bounding_box(lat: float, km: float) -> tuple[float, float, float]:
    """The box that holds every point within `km` of a point at latitude `lat`.

    Returns `(lat_lo, lat_hi, dlon)`: such a point has a latitude in `[lat_lo, lat_hi]` and a
    longitude within `dlon` degrees of the centre's (modulo 360). The longitude span is the exact
    one of a spherical cap, `asin(sin r / cos lat)`; when the circle reaches a pole every longitude
    is a candidate and `dlon` is 180.
    """
    r = km / EARTH_RADIUS_KM
    dlat = math.degrees(r)
    lat_lo, lat_hi = lat - dlat, lat + dlat
    if lat_lo <= -90.0 or lat_hi >= 90.0:
        return max(-90.0, lat_lo), min(90.0, lat_hi), 180.0
    # Below a pole, r < 90° − |lat|, so sin r < cos lat and the asin is defined.
    dlon = math.degrees(math.asin(math.sin(r) / math.cos(math.radians(lat))))
    return lat_lo, lat_hi, min(180.0, dlon)
