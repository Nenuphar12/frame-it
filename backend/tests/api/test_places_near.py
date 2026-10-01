"""The `place near` filter clause and its picker (docs/organization.md §3)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.api.test_artworks import create, photo
from tests.api.test_organization import collection, query
from tests.conftest import make_jpeg, upload_bytes

API = "/api/v1"
KYOTO = (35.0116, 135.7681)
OSAKA = (34.6937, 135.5023)  # ~43 km from Kyoto
TOKYO = (35.6762, 139.6503)  # ~365 km from Kyoto


_shades = iter(range(10, 250, 7))


def located(local: TestClient, name: str, gps: tuple[float, float]) -> str:
    """A photo taken at `gps`, by upload — the same EXIF path as a phone's.

    Each gets its own pixels: photos alike but for their EXIF are one photo to the library.
    """
    upload_bytes(local, make_jpeg(900, 600, (next(_shades), 40, 90), gps=gps), name)
    by_name = {p["original_filename"]: p for p in local.get(f"{API}/photos").json()["items"]}
    photo_id: str = by_name[name]["id"]
    return photo_id


def near(lat: float, lon: float, km: float, label: str = "") -> dict[str, Any]:
    clause = {"field": "place", "op": "near", "value": {"lat": lat, "lon": lon, "km": km}}
    if label:
        clause["value"]["label"] = label  # type: ignore[index]
    return {"op": "and", "clauses": [clause]}


def ids(items: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in items}


def test_near_matches_artworks_by_their_photos_position(local: TestClient) -> None:
    kyoto = create(local, [located(local, "kyoto.jpg", KYOTO)])
    osaka = create(local, [located(local, "osaka.jpg", OSAKA)])
    tokyo = create(local, [located(local, "tokyo.jpg", TOKYO)])
    nowhere = create(local, [photo(local)])  # no GPS: never near anything
    # an artwork is near a place when one of its photos is
    pair = create(local, [located(local, "tokyo-2.jpg", TOKYO), photo(local, 800, 600)])

    assert ids(query(local, filter=near(*KYOTO, 10))) == {kyoto["id"]}
    assert ids(query(local, filter=near(*KYOTO, 50))) == {kyoto["id"], osaka["id"]}
    everything = ids(query(local, filter=near(*KYOTO, 500)))
    assert everything == {kyoto["id"], osaka["id"], tokyo["id"], pair["id"]}
    assert nowhere["id"] not in everything

    # the same clause is a smart collection
    smart = collection(local, "Kansai", kind="smart", filter=near(*KYOTO, 50, "Kyoto"))
    assert smart["item_count"] == 2
    listed = local.get(f"{API}/artworks", params={"collection_id": smart["id"]}).json()["items"]
    assert ids(listed) == {kyoto["id"], osaka["id"]}

    # the artworks the clause can never reach are counted
    assert local.get(f"{API}/places").json()["unlocated_artworks"] == 1


def test_near_crosses_the_antimeridian(local: TestClient) -> None:
    east = create(local, [located(local, "east.jpg", (-16.80, 179.95))])
    west = create(local, [located(local, "west.jpg", (-16.80, -179.95))])  # ~10.6 km apart
    far = create(local, [located(local, "far.jpg", (-16.80, 178.0))])
    assert ids(query(local, filter=near(-16.80, 179.99, 20))) == {east["id"], west["id"]}
    assert ids(query(local, filter=near(-16.80, -179.99, 20))) == {east["id"], west["id"]}
    assert far["id"] in ids(query(local, filter=near(-16.80, 179.99, 300)))


def test_the_picker_finds_places_by_name_the_librarys_first(local: TestClient) -> None:
    def search(q: str) -> list[dict[str, Any]]:
        res = local.get(f"{API}/places/search", params={"q": q})
        assert res.status_code == 200, res.text
        found: list[dict[str, Any]] = res.json()
        return found

    first = search("kyoto")[0]
    assert (first["name"], first["country"], first["photo_count"]) == ("Kyoto", "Japan", 0)
    assert abs(first["lat"] - KYOTO[0]) < 0.1 and abs(first["lon"] - KYOTO[1]) < 0.1
    # accents and case are ignored; a comma narrows by region or country
    assert search("sao paulo")[0]["name"] == "São Paulo"
    assert {p["admin1"] for p in search("paris, tex")} == {"Texas"}

    # "Paris" is a dozen places: the library's own place leads (GeoNames names this spot
    # "Paris 04 Hôtel-de-Ville"), then the places in a country the library knows
    located(local, "paris.jpg", (48.8566, 2.3522))
    found = search("paris")
    assert found[0]["photo_count"] == 1 and found[0]["country"] == "France"
    assert next(p["country"] for p in found if p["name"] == "Paris") == "France"
