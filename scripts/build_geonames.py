#!/usr/bin/env python3
"""Build the compact offline reverse-geocoding dataset from GeoNames (CC BY 4.0).

Usage: python scripts/build_geonames.py [--source-dir DIR]
Downloads cities1000.zip, admin1CodesASCII.txt and countryInfo.txt (unless present in DIR) and writes
backend/src/the_frame_v2/assets/geonames/cities1000.tsv.gz with columns:
name, lat, lon, admin1 name, country name.
"""

from __future__ import annotations

import argparse
import gzip
import io
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://download.geonames.org/export/dump/"
# Sections of cities (e.g. "Lyon 01") and historical/abandoned/destroyed places are not useful names.
EXCLUDED_FEATURE_CODES = {"PPLX", "PPLH", "PPLQ", "PPLW", "PPLCH"}
OUT = Path(__file__).resolve().parents[1] / "backend/src/the_frame_v2/assets/geonames/cities1000.tsv.gz"


def fetch(name: str, source_dir: Path | None) -> bytes:
    if source_dir and (source_dir / name).is_file():
        return (source_dir / name).read_bytes()
    with urllib.request.urlopen(BASE + name, timeout=120) as resp:  # noqa: S310 — fixed https URL
        data: bytes = resp.read()
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args()

    countries: dict[str, str] = {}
    for line in fetch("countryInfo.txt", args.source_dir).decode().splitlines():
        if line and not line.startswith("#"):
            cols = line.split("\t")
            countries[cols[0]] = cols[4]
    admin1: dict[str, str] = {}
    for line in fetch("admin1CodesASCII.txt", args.source_dir).decode().splitlines():
        cols = line.split("\t")
        if len(cols) >= 2:
            admin1[cols[0]] = cols[1]

    with zipfile.ZipFile(io.BytesIO(fetch("cities1000.zip", args.source_dir))) as zf:
        raw = zf.read("cities1000.txt").decode()
    rows = []
    for line in raw.splitlines():
        c = line.split("\t")
        if c[7] in EXCLUDED_FEATURE_CODES:
            continue
        name, lat, lon, cc, a1 = c[1], float(c[4]), float(c[5]), c[8], c[10]
        rows.append(
            f"{name}\t{lat:.4f}\t{lon:.4f}\t{admin1.get(f'{cc}.{a1}', '')}\t{countries.get(cc, cc)}"
        )
    rows.sort()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as fh:
        fh.write("\n".join(rows) + "\n")
    print(f"wrote {len(rows)} places to {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
