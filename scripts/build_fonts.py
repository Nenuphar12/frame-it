#!/usr/bin/env python3
"""Build the bundled caption fonts (SIL Open Font License) as static instances.

Usage: uv run --with fonttools python scripts/build_fonts.py [--source-dir DIR]

Downloads the variable fonts from google/fonts at a pinned commit (unless present in DIR), creates one
static TTF per weight with fontTools' instancer and gives each file a unique family name
(`TF <font id> <weight>`) so fontconfig/Pango never mixes them with fonts installed on the machine.
Writes backend/src/the_frame_v2/assets/fonts/<id>/<weight>.ttf, OFL.txt per font and manifest.json.
Spec: docs/rendering-spec.md (captions).
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

COMMIT = "965e9104ac4cab0d9dbf49baeeb0c3d3de68cbe0"
BASE = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/"
OUT = Path(__file__).resolve().parents[1] / "backend/src/the_frame_v2/assets/fonts"

FONTS: list[dict[str, object]] = [
    {
        "id": "cormorant-garamond",
        "name": "Cormorant Garamond",
        "category": "serif",
        "source": "ofl/cormorantgaramond/CormorantGaramond[wght].ttf",
        "weights": [400, 500, 600, 700],
        "axes": {},
    },
    {
        "id": "eb-garamond",
        "name": "EB Garamond",
        "category": "serif",
        "source": "ofl/ebgaramond/EBGaramond[wght].ttf",
        "weights": [400, 500, 600, 700],
        "axes": {},
    },
    {
        "id": "inter",
        "name": "Inter",
        "category": "sans-serif",
        "source": "ofl/inter/Inter[opsz,wght].ttf",
        "weights": [300, 400, 500, 600, 700],
        "axes": {"opsz": 32},  # display optical size: captions are large on a TV
    },
    {
        "id": "josefin-sans",
        "name": "Josefin Sans",
        "category": "sans-serif",
        "source": "ofl/josefinsans/JosefinSans[wght].ttf",
        "weights": [300, 400, 600, 700],
        "axes": {},
    },
]


def fetch(path: str, source_dir: Path | None) -> bytes:
    local = source_dir / path.replace("/", "_") if source_dir else None
    if local and local.is_file():
        return local.read_bytes()
    url = BASE + path.replace("[", "%5B").replace("]", "%5D")
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 — fixed https URL
        data: bytes = resp.read()
    if local:
        local.write_bytes(data)
    return data


def rename(font: TTFont, family: str) -> None:
    table = font["name"]
    for record in list(table.names):
        if record.nameID in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25):
            table.removeNames(nameID=record.nameID)
    for name_id, value in (
        (1, family),
        (2, "Regular"),
        (3, f"{family};the_frame_v2"),
        (4, family),
        (6, family.replace(" ", "-")),
    ):
        table.setName(value, name_id, 3, 1, 0x409)
    if "STAT" in font:
        del font["STAT"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, help="cache for downloaded files")
    args = parser.parse_args()
    if args.source_dir:
        args.source_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for spec in FONTS:
        font_id = str(spec["id"])
        metrics: dict[str, dict[str, int]] = {}
        source = str(spec["source"])
        data = fetch(source, args.source_dir)
        target_dir = OUT / font_id
        target_dir.mkdir(parents=True, exist_ok=True)
        license_path = source.rsplit("/", 1)[0] + "/OFL.txt"
        (target_dir / "OFL.txt").write_bytes(fetch(license_path, args.source_dir))
        weights = [int(w) for w in spec["weights"]]  # type: ignore[attr-defined]
        for weight in weights:
            source_path = target_dir / ".variable.ttf"
            source_path.write_bytes(data)
            font = TTFont(source_path)
            axes = {"wght": weight, **dict(spec["axes"])}  # type: ignore[call-overload]
            instance = instantiateVariableFont(font, axes)
            rename(instance, f"TF {font_id} {weight}")
            instance["OS/2"].usWeightClass = 400
            instance["OS/2"].fsSelection = (instance["OS/2"].fsSelection & ~0b100001) | 0b1000000
            instance.save(target_dir / f"{weight}.ttf")
            metrics[str(weight)] = {
                "units_per_em": int(instance["head"].unitsPerEm),
                "ascender": int(instance["hhea"].ascent),
                "descender": int(instance["hhea"].descent),
            }
            source_path.unlink()
        manifest.append(
            {
                "id": font_id,
                "name": spec["name"],
                "category": spec["category"],
                "weights": weights,
                "metrics": metrics,
                "license": "OFL-1.1",
                "source": f"https://github.com/google/fonts/blob/{COMMIT}/{source}",
            }
        )
        print(f"{font_id}: {weights}")
    (OUT / "manifest.json").write_text(json.dumps({"version": 1, "fonts": manifest}, indent=2) + "\n")


if __name__ == "__main__":
    main()
