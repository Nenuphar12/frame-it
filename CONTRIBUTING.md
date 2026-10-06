# Contributing

Thanks for looking. This is a small, self-hosted app with a deliberately narrow scope — read
[`docs/PLAN.md`](docs/PLAN.md) §1 and §16 before proposing a feature, because "out of scope for v1"
is a real list and most of what is on it was decided on purpose. What is planned next is §17
(the roadmap).

**If you are a coding agent, read [`AGENTS.md`](AGENTS.md) first.** It is the entry point, it is
kept current with the code, and it carries the invariants; the subsystem-specific gotchas — the things
that are not obvious from reading a file — are in [`docs/gotchas.md`](docs/gotchas.md).

## AI-assisted work

This codebase was written almost entirely by an AI coding agent under the maintainer's direction
(see *Written with AI* in the [README](README.md)), and AI-assisted contributions are welcome on
the same terms as any other: **you answer for what you submit.** Concretely:

- say so in the pull request description (commits here carry no `Co-Authored-By:` trailer);
- run `make check`, then verify the behaviour yourself (in a browser for UI work, on a copy of a
  real library for anything that touches stored data);
- write down what you did **not** verify, in `docs/progress.md`, the way the existing entries do.

## Getting set up

Requirements: Python 3.14 + [uv](https://docs.astral.sh/uv/), Node 22+ + pnpm, and a libvips with
AVIF support (installed for you by `pyvips[binary]`).

```sh
make install
make dev         # API on :8765 with reload, Vite on :5173 → open http://localhost:5173
make check       # everything that must pass before you commit
```

`make dev` goes through the Vite proxy, which adds `X-Forwarded-For`, so the browser is **not**
trusted as localhost: the first load asks for the setup code printed in the server log.
`uv run frame-it doctor` reports what the machine can decode.

**Working on the TV pages without a TV**: start the server with `FRAME_IT_FAKE_TV=1`. Every TV
is then one in-memory fake (`tv/fake.py`) — discovery finds it, pairing needs no prompt, pushes take
a little time per image so the progress shows — and nothing ever reaches a real TV. Development only
(`docs/tv-display.md` §10).

## The rules that matter

These are the ones a reviewer will actually ask about. The full list is `AGENTS.md` §Invariants
and `docs/PLAN.md` §15.

1. **Originals are never modified.** Everything else in the data directory is disposable.
2. **Geometry lives in two languages.** `backend/.../domain/` and `frontend/src/editor/core/` are
   mirrors. Change one, change the other, add a case to `CASES` in `tests/unit/test_conformance.py`,
   regenerate the fixtures, and *check the new expected numbers by hand*.
3. **An API change is a generated-types change**: `make gen-api` in the same commit.
4. **A schema change is a migration**: never edit an old one; test it on an empty **and** a seeded
   database.
5. **Every user-facing string goes through i18n** (`t("…")`), and every error carries a stable
   `code` translated as `errors.<code>`.
6. **No secure-context-only browser API** without a fallback — the app runs over plain HTTP on a
   LAN, so `crypto.subtle`, `randomUUID`, clipboard writes and service workers are unavailable.
7. **Pointer gestures batch into `requestAnimationFrame`.** One React render per mouse event
   freezes the tab for tens of seconds; this is a correctness rule, not a nicety.
8. **`AGENTS.md` is updated in the same change** as whatever it describes.

## Tests

Backend unit + API tests, geometry conformance in both languages, and a few golden images. There is
no frontend test suite by design (`docs/PLAN.md` §13), so UI work is verified by hand in a browser
and what was *not* verified is written down in `docs/progress.md`.

```sh
cd backend && uv run pytest            # add -k name
make conformance                       # the TypeScript half of the geometry fixtures
make golden-update                     # after an intended pixel change — review the PNGs!
```

The **same document** rendering to different pixels means bumping `RENDERER_VERSION`; an asset
change means bumping the manifest `version`. A new optional document field needs neither — but it
must be listed in `_LATER_DEFAULTS` (`domain/document.py`), or every artwork's render hash changes
and the whole library is re-rendered and re-sent to the TV (`docs/gotchas.md`).

## Commits and pull requests

- [Conventional Commits](https://www.conventionalcommits.org/): `feat(editor): …`, `fix(api): …`.
- One behaviour change per commit, with its spec update, its tests and its `AGENTS.md` edit.
- Say what you measured. "Faster" is not a claim; "22 ms → 12 ms on a 10k library
  (`scripts/bench_library.py`)" is.

## Assets

Only OFL, CC0 or CC BY, and every one of them recorded in [`NOTICE.md`](NOTICE.md) with its source
and licence. Fonts are built by `scripts/build_fonts.py`, textures by
`scripts/generate_textures.py`, place names by `scripts/build_geonames.py`.

## Licence

By contributing you agree that your contributions are licensed under the MIT Licence
([`LICENSE`](LICENSE)).
