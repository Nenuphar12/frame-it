# Third-party notices

Frame It itself is MIT-licensed (`LICENSE`). Everything below ships *inside* the package and
keeps its own licence.

Frame It is not affiliated with, endorsed or sponsored by Samsung. Samsung and The Frame are
trademarks of Samsung Electronics Co., Ltd.; they are named only to say which TV the app works
with.

## Assets

| Asset | Location | License |
|---|---|---|
| GeoNames cities1000, admin1 codes, country info | `backend/src/frame_it/assets/geonames/` | CC BY 4.0 — © GeoNames (https://www.geonames.org) |
| Cormorant Garamond (Christian Thalmann) | `backend/src/frame_it/assets/fonts/cormorant-garamond/` | SIL Open Font License 1.1 (`OFL.txt`) |
| EB Garamond (Georg Duffner, Octavio Pardo) | `backend/src/frame_it/assets/fonts/eb-garamond/` | SIL Open Font License 1.1 (`OFL.txt`) |
| Inter (Rasmus Andersson) | `backend/src/frame_it/assets/fonts/inter/` | SIL Open Font License 1.1 (`OFL.txt`) |
| Josefin Sans (Santiago Orozco) | `backend/src/frame_it/assets/fonts/josefin-sans/` | SIL Open Font License 1.1 (`OFL.txt`) |
| Mat textures (generated) | `backend/src/frame_it/assets/textures/` | CC0 1.0 |

Font files are static instances (renamed families `TF <id> <weight>`) of the variable fonts published in
https://github.com/google/fonts, built by `scripts/build_fonts.py`; the OFL permits this as modified versions
under the same license (no Reserved Font Name is used).

## Screenshots

The photographs in `docs/images/` are from [Unsplash](https://unsplash.com) and are used under the
[Unsplash License](https://unsplash.com/license). They are demo content for the screenshots only —
none of them ships in the application. The filenames in the screenshots name the photographers:
Frank Huang, Mavis Hopper, Karsten Winegeart, Pascal Debrunner, Marek Piwnicki, Martin Makaryan,
Bruno BD and Jamo Images.

## Runtime dependencies

Talking to a Samsung Frame uses [samsungtvws](https://github.com/xchwarze/samsung-tv-ws-api)
(LGPL-3.0-or-later), imported unmodified as a library; the art-mode protocol it implements is
reverse-engineered, not documented by Samsung.

Image processing is done by [libvips](https://www.libvips.org/) (LGPL-2.1-or-later) through
`pyvips`; the wheels installed by `pyvips[binary]` carry their own bundled codecs and notices.
The rest of the Python and JavaScript dependencies are permissively licensed (MIT / BSD / Apache-2.0)
and are not redistributed in this repository — `uv.lock` and `pnpm-lock.yaml` pin exactly what an
install pulls.

## ICC profiles

None are bundled. Photos carrying an embedded profile are converted to sRGB by libvips' own
`icc_transform` (perceptual intent), and photos without one are interpreted as sRGB
(`imaging/decode.py`). The sRGB profile used for output is libvips' built-in one.
