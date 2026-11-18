#!/usr/bin/env python3
"""The date badge test (`docs/research/tv-display.md` §2c): which date does One UI Tizen 10 show?

Since the update, art mode shows a date in a bottom corner at every slideshow transition. This
uploads three labelled images, each carrying a different `image_date`, shows the first and starts
an **ordered** 3-minute slideshow, which walks the TV's list (newest upload first) from there:

    A — image_date "1999:12:31 12:00:00"  → does the badge read 31/12/1999? (it shows image_date)
    B — image_date ""                      → does a blank date hide the badge?
    C — image_date "2015:06:15 09:30:00"   → uploaded first, dated later than A: if the TV goes
                                             A → B → C it follows the upload order, not the dates

Watch the TV through two transitions (about 7 minutes) and note, for each image, the date in the
corner (or none) and the letter of the next one. Then delete the three and restore the app's
slideshow:

    cd backend
    uv run python ../scripts/tv_date_test.py images --out /tmp/date-test   # look first, no TV
    uv run python ../scripts/tv_date_test.py run
    uv run python ../scripts/tv_date_test.py cleanup
    uv run frame-it tv push <target id> --data-dir ../.dev-data    # the app's slideshow back

The TV and its token come from the library's display target (`--data-dir`, `--target`). `cleanup`
deletes exactly the ids `run` recorded in its state file — the app's own uploads are never
touched, and until `cleanup` the three images count as "not from this app" in the TV page.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FONT = REPO / "backend" / "src" / "frame_it" / "assets" / "fonts" / "inter" / "600.ttf"
WIDTH, HEIGHT = 3840, 2160
MINUTES = 3


@dataclass(frozen=True, slots=True)
class Variant:
    letter: str
    image_date: str
    shown_as: str
    """What the image itself says was sent, in the TV's day/month/year."""
    color: tuple[int, int, int]


#: Upload order is C, B, A: A is the newest upload, so the TV lists it first.
VARIANTS = (
    Variant("A", "1999:12:31 12:00:00", "31/12/1999", (24, 48, 96)),
    Variant("B", "", "vide", (24, 80, 48)),
    Variant("C", "2015:06:15 09:30:00", "15/06/2015", (96, 32, 32)),
)


def label_image(variant: Variant) -> bytes:
    """A 3840×2160 JPEG: a big letter and what was sent, clear of the bottom corners."""
    import pyvips

    markup = (
        f'<span size="300%"><b>{variant.letter}</b></span>\n'
        f"Date envoyée à la TV : {variant.shown_as}\n\n"
        '<span size="60%">Notez la date affichée dans le coin, ou son absence,\n'
        "puis la lettre de l'image suivante.</span>"
    )
    text = pyvips.Image.text(
        markup, fontfile=str(FONT), font="Inter 40", dpi=300, width=3200, align="centre"
    )
    background = pyvips.Image.black(WIDTH, HEIGHT, bands=3) + list(variant.color)
    left = (WIDTH - text.width) // 2
    top = (HEIGHT - text.height) // 2 - 120
    mask = text.embed(left, top, WIDTH, HEIGHT)
    image = mask.ifthenelse([255, 255, 255], background, blend=True).cast("uchar")
    data: bytes = image.jpegsave_buffer(Q=90)
    return data


def target_of(data_dir: Path, target_id: str | None) -> tuple[str, str, str]:
    """`(id, host, token)` of the library's TV, read-only."""
    db = data_dir / "library.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("select id, host, token from display_targets").fetchall()
    con.close()
    rows = [r for r in rows if target_id in (None, r[0])]
    if len(rows) != 1:
        sys.exit(f"{len(rows)} display targets match in {db}: pass --target")
    tv_id, host, token = rows[0]
    if not token:
        sys.exit("that TV is not paired")
    return str(tv_id), str(host), str(token)


def run(args: argparse.Namespace) -> None:
    from frame_it.tv.client import SamsungTvClient

    tv_id, host, token = target_of(args.data_dir, args.target)
    if args.state.exists():
        sys.exit(f"{args.state} exists: run `cleanup` first (it holds the ids of an earlier run)")
    state: dict[str, object] = {"target": tv_id, "host": host, "uploaded": {}}
    uploaded: dict[str, str] = {}
    args.state.parent.mkdir(parents=True, exist_ok=True)
    with SamsungTvClient(host, token) as tv:
        for variant in reversed(VARIANTS):  # C, B, A: A ends up first in the TV's list
            content_id = tv.upload(label_image(variant), "jpg", image_date=variant.image_date)
            uploaded[variant.letter] = content_id
            state["uploaded"] = uploaded
            args.state.write_text(json.dumps(state, indent=2))  # cleanup knows it, whatever next
            print(f"uploaded {variant.letter} as {content_id} (image_date {variant.image_date!r})")
            time.sleep(2)
        dates = {i.content_id: i.image_date for i in tv.items()}
        for variant in VARIANTS:
            stored = dates.get(uploaded[variant.letter])
            print(f"  the TV lists {variant.letter} with image_date {stored!r}")
        tv.stop_slideshow()
        tv.select(uploaded["A"])
        tv.start_slideshow(MINUTES, ordered=True)
    now = datetime.now()
    print(f"\nA is on screen since {now:%H:%M}. An ordered slideshow every {MINUTES} min runs from")
    print("there: watch the two next transitions and note, for each image, the date in the corner")
    print("(or none) and the letter that comes next. Then: cleanup, and re-push with the app.")


def cleanup(args: argparse.Namespace) -> None:
    from frame_it.tv.client import SamsungTvClient

    if not args.state.exists():
        sys.exit(f"nothing to clean up: no {args.state}")
    state = json.loads(args.state.read_text())
    ids = list(state.get("uploaded", {}).values())
    _, _, token = target_of(args.data_dir, state.get("target"))
    with SamsungTvClient(state["host"], token) as tv:
        on_tv = {i.content_id for i in tv.items()}
        tv.delete([i for i in ids if i in on_tv])
        left = {i.content_id for i in tv.items()} & set(ids)
    if left:
        sys.exit(f"still on the TV: {sorted(left)} — state kept in {args.state}")
    args.state.unlink()
    print(f"deleted {', '.join(ids) or 'nothing'}. Now restore the app's slideshow:")
    print(f"  uv run frame-it tv push {state['target']} --data-dir {args.data_dir}")


def images(args: argparse.Namespace) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    for variant in VARIANTS:
        path = args.out / f"{variant.letter}.jpg"
        path.write_bytes(label_image(variant))
        print(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=("images", "run", "cleanup"))
    parser.add_argument("--data-dir", type=Path, default=REPO / ".dev-data", help="the library")
    parser.add_argument("--target", help="display target id (default: the only one)")
    parser.add_argument(
        "--state",
        type=Path,
        default=REPO / ".dev-data" / "tv-probe" / "date-test.json",
        help="where `run` records the ids `cleanup` deletes",
    )
    parser.add_argument("--out", type=Path, default=Path("date-test"), help="`images` only")
    args = parser.parse_args()
    {"images": images, "run": run, "cleanup": cleanup}[args.command](args)


if __name__ == "__main__":
    main()
