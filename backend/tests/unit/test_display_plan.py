"""`plan_push`, the pure half of a push (`services/display.py`): what is reused, uploaded, removed.

The rules it encodes: in slideshow mode the TV's newest-first list must end up in set order, so
only a tail of the set can be reused; "Don't change" reuses any upload of the right render and
leaves everything else; an upload the TV no longer holds is forgotten; nothing that is not in the
map is ever ours.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from frame_it.services.display import MapRow, plan_push

T0 = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def row(
    artwork: str, content: str, minute: int, *, render: str = "h", position: int | None = 0
) -> MapRow:
    return MapRow(
        id=f"row-{content}",
        artwork_id=artwork,
        render_hash=render,
        content_id=content,
        position=position,
        uploaded_at=T0 + timedelta(minutes=minute),
    )


def wanted(*artworks: str) -> list[tuple[str, str]]:
    return [(a, "h") for a in artworks]


def test_first_push_uploads_everything_last_position_first() -> None:
    plan = plan_push(wanted("a", "b", "c"), [], set(), static=False)
    assert plan.upload == [2, 1, 0]
    assert plan.reuse == {}
    assert plan.remove_ours == [] and plan.foreign == []


def test_same_set_again_reuses_everything() -> None:
    # Uploaded in reverse: c first (oldest), a last (newest).
    rows = [row("c", "C", 0), row("b", "B", 1), row("a", "A", 2)]
    plan = plan_push(wanted("a", "b", "c"), rows, {"A", "B", "C"}, static=False)
    assert plan.upload == []
    assert {p: r.content_id for p, r in plan.reuse.items()} == {0: "A", 1: "B", 2: "C"}


def test_a_changed_middle_image_is_uploaded_with_everything_before_it() -> None:
    # b's render changed: uploading only b would make it the newest item, ahead of a.
    rows = [row("c", "C", 0), row("b", "B", 1, render="old"), row("a", "A", 2)]
    plan = plan_push(wanted("a", "b", "c"), rows, {"A", "B", "C"}, static=False)
    assert plan.upload == [1, 0]
    assert {p: r.content_id for p, r in plan.reuse.items()} == {2: "C"}
    assert sorted(r.content_id for r in plan.remove_ours) == ["A", "B"]


def test_a_changed_first_image_is_the_only_upload() -> None:
    rows = [row("c", "C", 0), row("b", "B", 1), row("a", "A", 2, render="old")]
    plan = plan_push(wanted("a", "b", "c"), rows, {"A", "B", "C"}, static=False)
    assert plan.upload == [0]
    assert [r.content_id for r in plan.remove_ours] == ["A"]


def test_reordering_keeps_only_the_tail_that_is_still_in_order() -> None:
    rows = [row("c", "C", 0), row("b", "B", 1), row("a", "A", 2)]
    # New order b, a, c: c is still the oldest and a newer than c, but b is older than a.
    plan = plan_push(wanted("b", "a", "c"), rows, {"A", "B", "C"}, static=False)
    assert {p: r.content_id for p, r in plan.reuse.items()} == {2: "C", 1: "A"}
    assert plan.upload == [0]
    assert [r.content_id for r in plan.remove_ours] == ["B"]


def test_slideshow_mode_removes_ours_outside_the_set_and_reports_foreign() -> None:
    rows = [row("x", "X", 0, position=None), row("a", "A", 1)]
    plan = plan_push(wanted("a"), rows, {"A", "X", "THEIRS"}, static=False)
    assert [r.content_id for r in plan.remove_ours] == ["X"]
    assert plan.foreign == ["THEIRS"]
    assert plan.leave_ours == []


def test_dont_change_reuses_any_position_and_leaves_ours_alone() -> None:
    rows = [row("c", "C", 0), row("b", "B", 1), row("a", "A", 2)]
    plan = plan_push(wanted("c", "a", "new"), rows, {"A", "B", "C", "THEIRS"}, static=True)
    assert {p: r.content_id for p, r in plan.reuse.items()} == {0: "C", 1: "A"}
    assert plan.upload == [2]
    assert plan.remove_ours == []
    assert [r.content_id for r in plan.leave_ours] == ["B"]
    assert plan.foreign == ["THEIRS"]


def test_an_upload_the_tv_lost_is_forgotten_and_uploaded_again() -> None:
    rows = [row("b", "B", 0), row("a", "A", 1)]
    plan = plan_push(wanted("a", "b"), rows, {"B"}, static=False)
    assert plan.gone == ["row-A"]
    assert plan.upload == [0]
    assert {p: r.content_id for p, r in plan.reuse.items()} == {1: "B"}


def test_without_the_tv_the_map_is_believed() -> None:
    rows = [row("b", "B", 0), row("a", "A", 1)]
    plan = plan_push(wanted("a", "b"), rows, None, static=False)
    assert plan.gone == [] and plan.foreign == []
    assert plan.upload == []


def test_one_upload_serves_one_position() -> None:
    # Two rows of the same render (an earlier crash, say): each can serve once, the newest first
    # in "Don't change", and the surplus is left alone.
    rows = [row("a", "A1", 0), row("a", "A2", 1)]
    plan = plan_push(wanted("a"), rows, {"A1", "A2"}, static=True)
    assert plan.reuse[0].content_id == "A2"
    assert [r.content_id for r in plan.leave_ours] == ["A1"]
