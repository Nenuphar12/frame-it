from __future__ import annotations

from pathlib import Path

import pytest
import pyvips

from frame_it.imaging import capabilities, decode
from frame_it.imaging.metadata import is_wide_gamut, parse_exif
from frame_it.imaging.sniff import sniff_bytes
from tests.conftest import make_jpeg

BASE_RGB = [200, 100, 50]


def _base(w: int = 300, h: int = 200) -> pyvips.Image:
    return (pyvips.Image.black(w, h, bands=3) + BASE_RGB).cast("uchar")


@pytest.mark.parametrize(
    ("head", "kind"),
    [
        (b"\xff\xd8\xff\xe0", "jpeg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf", "avif"),
        (b"\x00\x00\x00\x1cftypmif1\x00\x00\x00\x00mif1avifmiaf", "avif"),
        (b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic", "heic"),
        (b"\x00\x00\x00\x14ftypmif1\x00\x00\x00\x00mif1", "heif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
        (b"GIF89a", "gif"),
        (b"hello world", "unknown"),
    ],
)
def test_sniff(head: bytes, kind: str) -> None:
    assert sniff_bytes(head).kind == kind


def test_capabilities_complete() -> None:
    caps = capabilities.detect()
    assert caps.missing_required == []


def test_parse_exif_datetime_gps_and_camera() -> None:
    img = pyvips.Image.new_from_buffer(make_jpeg(gps=(-33.8688, 151.2093)), "")
    meta = parse_exif(img.get("exif-data"))
    assert meta.camera_make == "TestCam" and meta.camera_model == "Model X"
    assert meta.taken_at is not None and meta.taken_at.isoformat() == "2026-04-12T10:30:00+00:00"
    assert meta.gps_lat == pytest.approx(-33.8688, abs=1e-3)
    assert meta.gps_lon == pytest.approx(151.2093, abs=1e-3)


def test_parse_exif_detects_redacted_location() -> None:
    redacted = pyvips.Image.new_from_buffer(make_jpeg(gps_redacted=True), "")
    meta = parse_exif(redacted.get("exif-data"))
    assert meta.gps_lat is None and meta.location_removed
    located = pyvips.Image.new_from_buffer(make_jpeg(gps=(48.85, 2.35)), "")
    assert not parse_exif(located.get("exif-data")).location_removed
    assert not parse_exif(
        pyvips.Image.new_from_buffer(make_jpeg(), "").get("exif-data")
    ).location_removed


def test_parse_exif_tolerates_garbage() -> None:
    assert parse_exif(b"Exif\x00\x00garbage").has_capture_info is False
    assert parse_exif(None).taken_at is None


def test_wide_gamut_markers() -> None:
    assert is_wide_gamut("Display P3") and is_wide_gamut("sP3C")
    assert not is_wide_gamut("sRGB IEC61966-2.1") and not is_wide_gamut(None)


def test_p3_is_converted_to_srgb(tmp_path: Path) -> None:
    img = _base().copy()
    p3_profile = _base().icc_transform("p3", input_profile="srgb").get("icc-profile-data")
    img.set_type(pyvips.GValue.blob_type, "icc-profile-data", p3_profile)
    path = tmp_path / "p3.jpg"
    img.jpegsave(str(path), Q=98)
    probe = decode.probe(path, 10**9)
    assert probe.metadata.is_wide_gamut
    px = decode.load_srgb(path)(10, 10)
    # P3 (200,100,50) is more saturated than sRGB (200,100,50)
    assert px[0] > 205 and px[2] < 45


def test_orientation_applied(tmp_path: Path) -> None:
    path = tmp_path / "o.jpg"
    path.write_bytes(make_jpeg(300, 200, orientation=6))
    probe = decode.probe(path, 10**9)
    assert (probe.width, probe.height, probe.orientation) == (200, 300, 6)
    assert (decode.make_proxy(path).width, decode.load_srgb(path).height) == (200, 300)


@pytest.mark.parametrize("variant", ["png16", "alpha", "cmyk", "avif", "grey"])
def test_variants_decode_to_srgb8(tmp_path: Path, variant: str) -> None:
    base = _base(64, 48)
    path = (
        tmp_path / f"img.{'avif' if variant == 'avif' else 'jpg' if variant == 'cmyk' else 'png'}"
    )
    if variant == "png16":
        (base.cast("ushort") * 257).copy(interpretation="rgb16").pngsave(str(path), bitdepth=16)
    elif variant == "alpha":
        base.bandjoin(255).pngsave(str(path))
    elif variant == "cmyk":
        cmyk = (pyvips.Image.black(64, 48, bands=4) + [0, 255, 255, 0]).cast("uchar")
        cmyk.copy(interpretation="cmyk").jpegsave(str(path))
    elif variant == "avif":
        base.heifsave(str(path), compression="av1", Q=95)
    else:
        base.colourspace("b-w").pngsave(str(path))
    out = decode.load_srgb(path)
    assert (out.bands, out.format, out.interpretation) == (3, "uchar", "srgb")
    if variant in ("png16", "alpha"):
        assert [round(v) for v in out(5, 5)] == BASE_RGB
    probe = decode.probe(path, 10**9)
    assert probe.width == 64
    if variant == "png16":
        assert probe.bit_depth == 16


def test_rejections(tmp_path: Path) -> None:
    heic = tmp_path / "a.heic"
    heic.write_bytes(b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 32)
    with pytest.raises(decode.DecodeError) as exc:
        decode.probe(heic, 10**9)
    assert exc.value.code == "unsupported_format_heic"
    big = tmp_path / "big.jpg"
    big.write_bytes(make_jpeg(400, 300))
    with pytest.raises(decode.DecodeError) as exc:
        decode.probe(big, 1000)
    assert exc.value.code == "image_too_large"
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"GIF89a" + b"\x00" * 20)
    with pytest.raises(decode.DecodeError) as exc:
        decode.probe(gif, 10**9)
    assert exc.value.code == "unsupported_format"


def test_proxy_never_upscales_and_thumbs_written(tmp_path: Path) -> None:
    src = tmp_path / "s.jpg"
    src.write_bytes(make_jpeg(5000, 1000))
    proxy, thumbs = tmp_path / "p.jpg", {256: tmp_path / "256.webp", 768: tmp_path / "768.webp"}
    decode.write_proxy_and_thumbs(src, proxy, thumbs)
    p = pyvips.Image.new_from_file(str(proxy))
    assert (p.width, p.height) == (2560, 512)
    assert pyvips.Image.new_from_file(str(thumbs[256])).width == 256
    small = tmp_path / "small.jpg"
    small.write_bytes(make_jpeg(100, 50))
    assert decode.make_proxy(small).width == 100
