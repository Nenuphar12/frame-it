#!/usr/bin/env python3
"""Seed a library with many artworks, to browse a realistic one (docs/PLAN.md §14, Phase 9 AC).

Usage:
    cd backend && uv run python ../scripts/seed_library.py --data-dir /tmp/seed --artworks 10000

A few dozen real originals are written and given their derivatives, then the artworks are **rows**
reusing them: the acceptance criterion is about 10k items in the grid, the filter bar, the
collection tree and the FTS index, not about 10k distinct renders.

Point `--data-dir` at a scratch directory: this fills a normal library.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import random
from datetime import timedelta
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from frame_it.config import Settings
from frame_it.context import AppContext
from frame_it.db.models import Artwork, ArtworkPhoto, ArtworkTag, CollectionItem, Photo, Tag
from frame_it.ids import utcnow
from frame_it.imaging.fingerprint import content_fingerprint
from frame_it.services import artworks as artworks_service
from frame_it.services import collections as collections_service
from frame_it.services import search
from frame_it.services.ingest import ensure_derivatives

PLACES = ["Kyoto", "Lisbon", "Reykjavík", "Oaxaca", "Hanoi", "Tromsø", "Valparaíso"]
WORDS = ["dawn", "harbour", "market", "temple", "ridge", "fog", "canal", "dunes", "rooftops"]
TAG_NAMES = ["travel", "family", "black & white", "winter", "architecture", "sea", "night"]
SIZES = [(4000, 3000), (3000, 4000), (5000, 3333), (2400, 2400), (6000, 4000)]


def _jpeg(seed: int) -> tuple[bytes, tuple[int, int]]:
    rng = random.Random(seed)  # noqa: S311 — sample data, not secrets
    size = SIZES[seed % len(SIZES)]
    image = Image.new("RGB", size, tuple(rng.randint(30, 220) for _ in range(3)))
    # A little structure, so thumbnails are not flat squares and the palette has something to find.
    for _ in range(12):
        x, y = rng.randint(0, size[0]), rng.randint(0, size[1])
        patch_size = (rng.randint(50, 900), rng.randint(50, 900))
        color = tuple(rng.randint(0, 255) for _ in range(3))
        image.paste(Image.new("RGB", patch_size, color), (x, y))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return buffer.getvalue(), size


def seed_photos(ctx: AppContext, count: int) -> list[str]:
    ids: list[str] = []
    for seed in range(count):
        data, (width, height) = _jpeg(seed)
        sha = hashlib.sha256(data).hexdigest()
        path: Path = ctx.storage.original_path(sha, "jpg")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        ensure_derivatives(ctx, sha, path)
        rng = random.Random(seed)  # noqa: S311 — sample data, not secrets
        with ctx.db.session() as session:
            photo = Photo(
                sha256=sha,
                content_fingerprint=content_fingerprint(path, "jpg"),
                ext="jpg",
                mime="image/jpeg",
                original_filename=f"SEED_{seed:04d}.jpg",
                file_size=len(data),
                width=width,
                height=height,
                inbox_state="processed",
                place_name=rng.choice(PLACES),
                camera_model="Seed 1",
                taken_at=utcnow() - timedelta(days=rng.randint(0, 1500)),
            )
            session.add(photo)
            session.flush()
            search.index_photo(session, photo)
            ids.append(photo.id)
        print(f"  photo {len(ids)}/{count}", end="\r")
    print()
    return ids


def seed_artworks(
    session: Session, photo_ids: list[str], count: int, collection_count: int
) -> None:
    rng = random.Random(7)  # noqa: S311 — sample data, not secrets
    tags = [Tag(name=name) for name in TAG_NAMES]
    session.add_all(tags)
    session.flush()
    roots = [
        collections_service.create_collection(session, name=f"Collection {n + 1}")
        for n in range(max(1, min(collection_count, 8)))
    ]
    collections = list(roots)
    for n in range(collection_count - len(roots)):
        parent = roots[n % len(roots)]
        collections.append(
            collections_service.create_collection(
                session, name=f"{parent.name} · part {n + 1}", parent_id=parent.id
            )
        )
    collections_service.create_collection(
        session,
        name="Favorites, ready",
        kind="smart",
        filter_ast={
            "op": "and",
            "clauses": [
                {"field": "favorite", "op": "eq", "value": True},
                {"field": "status", "op": "eq", "value": "ready"},
            ],
        },
    )
    # One real artwork per photo gives valid documents; the rest are clones of those. The clone
    # must carry the *same* photo in its document and in its `artwork_photos` index — the trash
    # cascade reads the index to find affected artworks and the document to empty their slots.
    templates = [artworks_service.create_artwork(session, [photo_id]) for photo_id in photo_ids]
    now = utcnow()
    for n in range(count - len(templates)):
        source = templates[n % len(templates)]
        artwork = Artwork(
            title=f"{rng.choice(PLACES)} {rng.choice(WORDS)} {n + 1}",
            status="ready" if n % 3 else "draft",
            document=dict(source.document),
            favorite=n % 11 == 0,
            worst_tier=source.worst_tier,
            min_scale=source.min_scale,
            max_scale=source.max_scale,
            photo_count=1,
            created_at=now - timedelta(minutes=n),
            updated_at=now - timedelta(minutes=n),
        )
        session.add(artwork)
        session.flush()
        slot = source.document["slots"][0]
        session.add(
            ArtworkPhoto(
                artwork_id=artwork.id, slot_id=str(slot["id"]), photo_id=str(slot["photo_id"])
            )
        )
        session.add(ArtworkTag(artwork_id=artwork.id, tag_id=rng.choice(tags).id))
        if n % 3 == 0:
            session.add(
                CollectionItem(
                    collection_id=rng.choice(collections).id,
                    artwork_id=artwork.id,
                    position=float(n),
                )
            )
        search.index_artwork(session, artwork)
        if n % 500 == 0:
            print(f"  artwork {n}/{count}", end="\r")
    print(f"  artwork {count}/{count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artworks", type=int, default=10_000)
    parser.add_argument("--photos", type=int, default=30, help="distinct originals to write")
    parser.add_argument("--collections", type=int, default=40)
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args()

    from frame_it.app import build_context

    settings = Settings(data_dir=args.data_dir) if args.data_dir else Settings()
    print(f"seeding {settings.data_dir}")
    ctx = build_context(settings)
    photo_ids = seed_photos(ctx, args.photos)
    with ctx.db.session() as session:
        seed_artworks(session, photo_ids, args.artworks, args.collections)
    print("done — serve this data dir to browse it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
