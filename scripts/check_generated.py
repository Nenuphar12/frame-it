"""Fail when the generated API files are older than the backend (`make generated`, in `make check`).

`make gen-api` writes `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts` and
`docs/schemas/`. This writes them again into a temporary directory, the same way, and compares: an
API model or a document schema cannot change without its generated files (invariant 6).

Run from `backend/`: `uv run python ../scripts/check_generated.py`.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)  # noqa: S603


def _files(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def stale_files() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        _run(["uv", "run", "frame-it", "openapi", "-o", str(tmp / "openapi.json")], BACKEND)
        _run(["uv", "run", "frame-it", "schemas", "-o", str(tmp / "schemas")], BACKEND)
        _run(
            [
                "pnpm",
                "exec",
                "openapi-typescript",
                str(tmp / "openapi.json"),
                "-o",
                str(tmp / "schema.d.ts"),
            ],
            FRONTEND,
        )
        stale = [
            str(committed.relative_to(ROOT))
            for fresh, committed in (
                (tmp / "openapi.json", FRONTEND / "src/api/openapi.json"),
                (tmp / "schema.d.ts", FRONTEND / "src/api/schema.d.ts"),
            )
            if not committed.is_file() or committed.read_bytes() != fresh.read_bytes()
        ]
        fresh_schemas, committed_schemas = _files(tmp / "schemas"), _files(ROOT / "docs/schemas")
        stale += [
            f"docs/schemas/{name}"
            for name in sorted(fresh_schemas.keys() | committed_schemas.keys())
            if fresh_schemas.get(name) != committed_schemas.get(name)
        ]
    return stale


def main() -> int:
    stale = stale_files()
    if stale:
        print("Stale generated files (run `make gen-api`):", *stale, sep="\n  ")
        return 1
    print("Generated files up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
