from __future__ import annotations

from pathlib import Path

from frame_it.imaging.fingerprint import content_fingerprint, file_sha256
from frame_it.services.photo_copies import is_generated_name
from tests.conftest import make_jpeg


def test_jpeg_fingerprint_ignores_exif_only(tmp_path: Path) -> None:
    paths = {}
    for name, data in {
        "located": make_jpeg(gps=(1.0, 2.0)),
        "redacted": make_jpeg(gps_redacted=True),
        "other": make_jpeg(color=(1, 2, 3)),
    }.items():
        paths[name] = tmp_path / f"{name}.jpg"
        paths[name].write_bytes(data)
    fp = {name: content_fingerprint(path, "jpeg") for name, path in paths.items()}
    assert fp["located"] == fp["redacted"] != fp["other"]


def test_non_jpeg_and_broken_streams_fall_back_to_file_hash(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"\xff\xd8\xff\xe1\x00")
    assert content_fingerprint(broken, "jpeg") == file_sha256(broken)
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG....")
    assert content_fingerprint(png, "png") == file_sha256(png)


def test_generated_names() -> None:
    assert is_generated_name("1000125423.jpg")
    assert not is_generated_name("PXL_20260917_082757358.MP.jpg")
    assert not is_generated_name("IMG_1234.jpg")
