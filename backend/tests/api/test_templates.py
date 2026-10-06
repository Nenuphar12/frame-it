"""Frame styles and layouts: CRUD, save-as, apply, push update, template files.

Spec: docs/templates.md. The rule these tests exist for is `PLAN.md` §4 rule 6 — a template is
copied on apply, so editing one never changes an artwork until the user pushes the update.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from frame_it.db.models import FrameStyle, Layout
from frame_it.services import templates
from tests.api.test_artworks import API, create, photo
from tests.conftest import ctx_of, pair

STYLE_DOC: dict[str, Any] = {
    "mat": {"color": "#101010", "texture": None},
    "margins": {"top": 200, "right": 200, "bottom": 260, "left": 200},
    "slot_defaults": {
        "bands": [{"width": 16, "color": "#FFFFFF"}],
        "shadow": {"type": "drop", "offset_x": 0, "offset_y": 10, "blur": 30, "opacity": 0.3},
    },
    "caption_defaults": {"font": "inter", "weight": 400, "size": 64, "color": "#222222"},
}
LAYOUT_DOC: dict[str, Any] = {
    "recipe": "two-side-by-side",
    "outer": {"x": 220, "y": 200},
    "gutter": {"x": 100, "y": 100},
    "format": "1:1",
}


def new_style(local: TestClient, name: str = "Ink", **over: Any) -> dict[str, Any]:
    body = {"name": name, "document": {**STYLE_DOC, **over}}
    res = local.post(f"{API}/frame-styles", json=body)
    assert res.status_code == 201, res.text
    created: dict[str, Any] = res.json()
    return created


def new_layout(local: TestClient, name: str = "Pair", **over: Any) -> dict[str, Any]:
    body = {"name": name, "document": {**LAYOUT_DOC, **over}}
    res = local.post(f"{API}/layouts", json=body)
    assert res.status_code == 201, res.text
    created: dict[str, Any] = res.json()
    return created


def test_style_crud_and_builtin_protection(local: TestClient) -> None:
    style = new_style(local)
    assert style["builtin"] is False and style["revision"] == 1
    assert style["document"]["mat"]["color"] == "#101010"

    renamed = local.patch(f"{API}/frame-styles/{style['id']}", json={"name": "Ink dark"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Ink dark"
    assert renamed.json()["revision"] == 1  # a rename is not a new look

    document = {**STYLE_DOC, "mat": {"color": "#FFFFFF", "texture": None}}
    changed = local.patch(f"{API}/frame-styles/{style['id']}", json={"document": document})
    assert changed.status_code == 200 and changed.json()["revision"] == 2

    copy = local.post(f"{API}/frame-styles/{style['id']}/duplicate", json={})
    assert copy.status_code == 201 and copy.json()["name"] == "Ink dark copy"
    assert copy.json()["document"] == changed.json()["document"]

    builtin = "builtin-style-linen"
    assert local.patch(f"{API}/frame-styles/{builtin}", json={"name": "x"}).status_code == 422
    assert local.delete(f"{API}/frame-styles/{builtin}").json()["code"] == "builtin_template"
    assert local.delete(f"{API}/frame-styles/{style['id']}").status_code == 204
    assert local.patch(f"{API}/frame-styles/{style['id']}", json={"name": "x"}).status_code == 422


def test_layout_is_a_recipe_and_its_parameters(local: TestClient) -> None:
    layout = new_layout(local)
    assert layout["slot_count"] == 2  # from the recipe, not from a list of rects
    assert layout["document"]["format"] == "1:1"

    bad = local.post(f"{API}/layouts", json={"name": "Nope", "document": {"recipe": "nope"}})
    assert bad.status_code == 422 and bad.json()["code"] == "unknown_recipe"
    invalid = local.post(
        f"{API}/layouts", json={"name": "Nope", "document": {**LAYOUT_DOC, "format": "zzz"}}
    )
    assert invalid.status_code == 422  # rejected by the request model itself
    # …and an imported file, whose document is free-form JSON, by the service (`invalid_template`)
    imported = local.post(
        f"{API}/layouts/import",
        json={
            "kind": "tflayout",
            "version": 1,
            "name": "Nope",
            "document": {**LAYOUT_DOC, "format": "zzz"},
        },
    )
    assert imported.status_code == 422 and imported.json()["code"] == "invalid_template"
    # per-split weights must describe *this* recipe's divisions (a two-part root here)
    misfit = local.post(
        f"{API}/layouts",
        json={"name": "Nope", "document": {**LAYOUT_DOC, "weights": [[1, 1, 1]]}},
    )
    assert misfit.status_code == 422 and misfit.json()["code"] == "invalid_template"
    weighted = local.post(
        f"{API}/layouts",
        json={
            "name": "Uneven",
            "document": {**LAYOUT_DOC, "weights": [[1, 3]], "caption_align": "left"},
        },
    )
    assert weighted.status_code == 201, weighted.text
    assert weighted.json()["document"]["weights"] == [[1.0, 3.0]]
    assert weighted.json()["document"]["caption_align"] == "left"

    moved = local.patch(
        f"{API}/layouts/{layout['id']}",
        json={"document": {**LAYOUT_DOC, "recipe": "three-row"}},
    )
    assert moved.status_code == 200
    assert moved.json()["slot_count"] == 3 and moved.json()["revision"] == 2


def test_create_from_a_layout_records_the_origin(local: TestClient) -> None:
    layout = new_layout(local)
    ids = [photo(local, 1200, 800), photo(local, 800, 1200)]
    artwork = create(local, ids, layout_id=layout["id"], style_id="builtin-style-thin-black")
    assert artwork["origin_layout_id"] == layout["id"]
    assert artwork["origin_layout_revision"] == 1
    block = artwork["document"]["composition"]
    assert block["recipe"] == "two-side-by-side" and block["format"] == "1:1"
    first, second = artwork["document"]["slots"]
    assert first["rect"]["w"] == first["rect"]["h"]  # 1:1 cells, as the layout asks
    assert second["rect"]["y"] == first["rect"]["y"]

    usage = local.get(f"{API}/layouts/{layout['id']}/usage").json()
    assert [item["id"] for item in usage] == [artwork["id"]]


def test_save_as_style_and_layout_from_an_artwork(local: TestClient) -> None:
    layout = new_layout(local)
    ids = [photo(local, 1200, 800), photo(local, 800, 1200)]
    artwork = create(local, ids, layout_id=layout["id"], style_id="builtin-style-linen")

    style = local.post(
        f"{API}/frame-styles/from-artwork", json={"artwork_id": artwork["id"], "name": "From art"}
    )
    assert style.status_code == 201, style.text
    assert style.json()["document"]["mat"]["color"] == artwork["document"]["mat"]["color"]

    saved = local.post(
        f"{API}/layouts/from-artwork", json={"artwork_id": artwork["id"], "name": "From art"}
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["document"]["recipe"] == "two-side-by-side"
    assert saved.json()["document"]["format"] == "1:1"
    assert saved.json()["slot_count"] == 2

    # A hand-placed artwork has no layout to save (§3).
    document = artwork["document"]
    document["composition"]["detached"] = True
    headers = {"If-Match": f'"{artwork["document_version"]}"'}
    assert (
        local.put(
            f"{API}/artworks/{artwork['id']}/document", json=document, headers=headers
        ).status_code
        == 200
    )
    detached = local.post(
        f"{API}/layouts/from-artwork", json={"artwork_id": artwork["id"], "name": "Nope"}
    )
    assert detached.status_code == 422 and detached.json()["code"] == "artwork_detached"


def test_apply_template_to_one_artwork(local: TestClient) -> None:
    ids = [photo(local, 1200, 800), photo(local, 800, 1200)]
    artwork = create(local, ids)
    layout = new_layout(local)
    style = new_style(local)

    applied = local.post(
        f"{API}/artworks/{artwork['id']}/apply-template",
        json={"style_id": style["id"], "layout_id": layout["id"]},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["origin_style_id"] == style["id"] and body["origin_layout_id"] == layout["id"]
    assert body["document"]["mat"]["color"] == "#101010"
    assert body["document"]["composition"]["format"] == "1:1"
    # the style's band became the block's border, so the solver owns the bands (§3)
    assert body["document"]["slots"][0]["bands"] == [
        {"width": 16, "color": "#FFFFFF", "bevel": False}
    ]
    assert body["document_version"] == artwork["document_version"] + 1

    # …and the change is undoable: a `pre_template_update` snapshot was taken first.
    snapshots = local.get(f"{API}/artworks/{artwork['id']}/snapshots").json()
    assert snapshots[0]["reason"] == "pre_template_update"
    restored = local.post(f"{API}/artworks/{artwork['id']}/snapshots/{snapshots[0]['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["document"]["mat"] == artwork["document"]["mat"]

    nothing = local.post(f"{API}/artworks/{artwork['id']}/apply-template", json={})
    assert nothing.status_code == 422 and nothing.json()["code"] == "nothing_to_apply"


def test_push_update_only_touches_the_template_s_artworks(local: TestClient) -> None:
    style = new_style(local)
    ids = [photo(local, 1200, 800), photo(local, 800, 1200)]
    mine = create(local, ids, style_id=style["id"])
    other = create(local, [ids[0]], style_id="builtin-style-linen")
    assert mine["document"]["mat"]["color"] == "#101010"

    # Editing the style leaves every artwork alone (copy on apply).
    document = {**STYLE_DOC, "mat": {"color": "#445566", "texture": None}}
    updated = local.patch(f"{API}/frame-styles/{style['id']}", json={"document": document}).json()
    assert updated["revision"] == 2
    unchanged = local.get(f"{API}/artworks/{mine['id']}").json()
    assert unchanged["document"]["mat"]["color"] == "#101010"
    assert unchanged["origin_style_revision"] == 1  # outdated: below the style's revision

    preview = local.post(f"{API}/frame-styles/{style['id']}/push-update/preview").json()
    assert preview["dry_run"] is True and preview["applied"] == 1 and preview["skipped"] == 0
    assert [item["artwork_id"] for item in preview["items"]] == [mine["id"]]
    assert local.get(f"{API}/artworks/{mine['id']}").json()["document"]["mat"]["color"] == "#101010"

    pushed = local.post(f"{API}/frame-styles/{style['id']}/push-update").json()
    assert pushed["dry_run"] is False and pushed["applied"] == 1
    after = local.get(f"{API}/artworks/{mine['id']}").json()
    assert after["document"]["mat"]["color"] == "#445566"
    assert after["origin_style_revision"] == 2  # up to date again
    assert (
        local.get(f"{API}/artworks/{other['id']}").json()["document"]["mat"]["color"] != "#445566"
    )

    # …and it is undoable, artwork by artwork, from the snapshot taken first.
    snapshots = local.get(f"{API}/artworks/{mine['id']}/snapshots").json()
    assert snapshots[0]["reason"] == "pre_template_update"
    restored = local.post(f"{API}/artworks/{mine['id']}/snapshots/{snapshots[0]['id']}/restore")
    assert restored.json()["document"]["mat"]["color"] == "#101010"


def test_push_update_skips_what_a_layout_cannot_touch(local: TestClient) -> None:
    layout = new_layout(local)
    ids = [photo(local, 1200, 800), photo(local, 800, 1200)]
    kept = create(local, ids, layout_id=layout["id"])
    detached = create(local, ids, layout_id=layout["id"])

    document = detached["document"]
    document["composition"]["detached"] = True
    headers = {"If-Match": f'"{detached["document_version"]}"'}
    local.put(f"{API}/artworks/{detached['id']}/document", json=document, headers=headers)

    local.patch(
        f"{API}/layouts/{layout['id']}",
        json={"document": {**LAYOUT_DOC, "gutter": {"x": 300, "y": 300}}},
    )
    preview = local.post(f"{API}/layouts/{layout['id']}/push-update/preview").json()
    reasons = {item["artwork_id"]: item["reason"] for item in preview["items"]}
    assert reasons[kept["id"]] is None and reasons[detached["id"]] == "detached"
    assert preview["applied"] == 1 and preview["skipped"] == 1

    local.post(f"{API}/layouts/{layout['id']}/push-update")
    after = local.get(f"{API}/artworks/{kept['id']}").json()["document"]
    first, second = after["slots"]
    assert second["rect"]["x"] - (first["rect"]["x"] + first["rect"]["w"]) == 300
    untouched = local.get(f"{API}/artworks/{detached['id']}").json()["document"]
    assert untouched["slots"] == document["slots"]


def test_template_files_round_trip(local: TestClient) -> None:
    style = new_style(local, name="Exported")
    exported = local.get(f"{API}/frame-styles/{style['id']}/export").json()
    assert exported["kind"] == "tfstyle" and exported["version"] == 1
    imported = local.post(f"{API}/frame-styles/import", json=exported)
    assert imported.status_code == 201, imported.text
    assert imported.json()["document"] == style["document"]
    assert imported.json()["id"] != style["id"]

    layout = new_layout(local, name="Exported")
    layout_file = local.get(f"{API}/layouts/{layout['id']}/export").json()
    assert layout_file["kind"] == "tflayout"
    assert local.post(f"{API}/layouts/import", json=layout_file).status_code == 201

    wrong = local.post(f"{API}/layouts/import", json=exported)
    assert wrong.status_code == 422 and wrong.json()["code"] == "wrong_template_kind"
    old = local.post(f"{API}/frame-styles/import", json={**exported, "version": 99})
    assert old.json()["code"] == "unsupported_template_version"


def test_templates_are_admin_only(local: TestClient) -> None:
    uploader = pair(local, "uploader")
    assert uploader.get(f"{API}/frame-styles").status_code == 403
    assert (
        uploader.post(f"{API}/layouts", json={"name": "x", "document": LAYOUT_DOC}).status_code
        == 403
    )


def test_a_schema_addition_does_not_outdate_the_builtins(local: TestClient) -> None:
    """A built-in stored before an optional field existed says the same thing without that key:
    seeding again must not call it a new revision — every artwork made from it would be flagged
    outdated, for a push update that changes nothing."""
    ctx = ctx_of(local)
    with ctx.db.session() as session:
        style = session.get(FrameStyle, "builtin-style-linen")
        layout = session.scalars(select(Layout).where(Layout.builtin)).first()
        assert style is not None and layout is not None
        layout_id = layout.id
        revisions = (style.revision, layout.revision)
        # as an older version of the app wrote them: without the fields added since
        old_style = {k: v for k, v in style.document.items() if k != "edge_shadow"}
        old_style["slot_defaults"] = {
            **old_style["slot_defaults"],
            "bands": [
                {"width": b["width"], "color": b["color"]}
                for b in style.document["slot_defaults"]["bands"]
            ],
        }
        style.document = old_style
        layout.document = {
            k: v for k, v in layout.document.items() if k not in ("weights", "caption_align")
        }
    with ctx.db.session() as session:
        templates.seed_builtins(session)
    with ctx.db.session() as session:
        style = session.get(FrameStyle, "builtin-style-linen")
        layout = session.get(Layout, layout_id)
        assert style is not None and layout is not None
        assert (style.revision, layout.revision) == revisions
        assert "edge_shadow" in style.document and "weights" in layout.document  # rewritten
        # a real change to a preset still is a new revision
        style.document = {**style.document, "mat": {"color": "#123456", "texture": None}}
    with ctx.db.session() as session:
        templates.seed_builtins(session)
    with ctx.db.session() as session:
        style = session.get(FrameStyle, "builtin-style-linen")
        assert style is not None and style.revision == revisions[0] + 1


def test_the_bevelled_mat_builds_a_bevelled_artwork(local: TestClient) -> None:
    """The built-in that looks like a Frame's own matte: a bevel around the photo, a frame shadow."""
    styles = {s["id"]: s for s in local.get(f"{API}/frame-styles").json()}
    style = styles["builtin-style-bevelled-mat"]["document"]
    assert style["slot_defaults"]["bands"] == [{"width": 12, "color": "#EFF1EF", "bevel": True}]
    assert style["edge_shadow"]["opacity"] == 0.22

    artwork = create(local, [photo(local, 2000, 1500)], style_id="builtin-style-bevelled-mat")
    document = artwork["document"]
    assert document["composition"]["border"] == {"width": 12, "color": "#EFF1EF", "bevel": True}
    assert document["slots"][0]["bands"] == [{"width": 12, "color": "#EFF1EF", "bevel": True}]
    assert document["edge_shadow"] == style["edge_shadow"]
    render = local.get(f"{API}/artworks/{artwork['id']}/render.png")
    assert render.status_code == 200
