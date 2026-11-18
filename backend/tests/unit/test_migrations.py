"""Migrations that touch rows other tables cascade from (docs/data-model.md)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import text

from frame_it.db.migrate import alembic_config, upgrade_to_head
from frame_it.db.session import Database

BEFORE_TAG_CATEGORIES = "32545e54fd09"  # 0010, the revision 0011 builds on
BEFORE_IMAGE_DATES = "83546c17327b"  # 0011, the revision 0012 builds on


def _upgrade_to(db: Database, revision: str) -> None:
    cfg = alembic_config()
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)


def test_tag_categories_keep_every_tag_link(tmp_path: Path) -> None:
    """0011 adds columns to `tags`, which `photo_tags`/`artwork_tags` cascade from.

    A batch rebuild would drop `tags` with foreign keys on — and delete every link. The migration
    alters the table in place instead; this pins it, and the default categories it seeds.
    """
    db = Database(tmp_path / "library.db")
    _upgrade_to(db, BEFORE_TAG_CATEGORIES)
    with db.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO tags (id, name, color, created_at) "
                "VALUES ('t1', 'Sea', NULL, '2026-01-01T00:00:00.000000Z')"
            )
        )
        c.execute(
            text(
                "INSERT INTO photos (id, sha256, ext, mime, original_filename, file_size, width,"
                " height, exif_orientation, bit_depth, is_wide_gamut, has_gain_map, imported_at,"
                " inbox_state, quality_warnings) VALUES ('p1', :sha, 'jpg', 'image/jpeg', 'a.jpg',"
                " 1, 1, 1, 1, 8, 0, 0, '2026-01-01T00:00:00.000000Z', 'inbox', '[]')"
            ),
            {"sha": "a" * 64},
        )
        c.execute(text("INSERT INTO photo_tags (photo_id, tag_id) VALUES ('p1', 't1')"))

    upgrade_to_head(db.engine)

    def rows(sql: str) -> list[tuple[object, ...]]:
        return [tuple(row) for row in c.execute(text(sql)).all()]

    with db.engine.begin() as c:
        assert rows("SELECT photo_id, tag_id FROM photo_tags") == [("p1", "t1")]
        assert rows("SELECT category_id, last_used_at FROM tags") == [(None, None)]
        names = c.execute(text("SELECT name FROM tag_categories ORDER BY position")).scalars()
        assert list(names) == ["People", "Events", "Themes"]
        # deleting a category sends its tags to "Other" (ON DELETE SET NULL), never deletes them
        c.execute(
            text(
                "UPDATE tags SET category_id = "
                "(SELECT id FROM tag_categories WHERE name = 'People')"
            )
        )
        c.execute(text("DELETE FROM tag_categories WHERE name = 'People'"))
        assert rows("SELECT id, category_id FROM tags") == [("t1", None)]


def test_image_dates_keep_every_record_of_what_is_on_the_tv(tmp_path: Path) -> None:
    """0012 drops a column of `display_targets`, which `display_target_items` cascades from.

    Its first version rebuilt the table in a batch — with foreign keys on, that deleted every
    item, and a real library's 42 uploads became "photos this app did not send". It alters in
    place now; the items stay, with no recorded date (the next push sends them again once).
    """
    db = Database(tmp_path / "library.db")
    _upgrade_to(db, BEFORE_IMAGE_DATES)
    with db.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO display_targets (id, name, host, slideshow_minutes,"
                " slideshow_ordered, render_format, state, created_at, image_clock)"
                " VALUES ('tv1', 'Living room', '192.0.2.10', 3, 0, 'jpg', 'ready',"
                " '2026-01-01T00:00:00.000000Z', '2026-01-01T00:00:00.000000Z')"
            )
        )
        c.execute(
            text(
                "INSERT INTO display_target_items (id, target_id, artwork_id, render_hash,"
                " content_id, position, uploaded_at) VALUES ('i1', 'tv1', 'a1', :hash,"
                " 'MY_F0001', 0, '2026-01-01T00:00:00.000000Z')"
            ),
            {"hash": "h" * 64},
        )

    upgrade_to_head(db.engine)

    with db.engine.begin() as c:
        items = c.execute(text("SELECT content_id, image_date FROM display_target_items")).all()
        assert [tuple(row) for row in items] == [("MY_F0001", None)]
        columns = [row[1] for row in c.execute(text("PRAGMA table_info(display_targets)"))]
        assert "image_clock" not in columns
        assert c.execute(text("SELECT host FROM display_targets")).scalar_one() == "192.0.2.10"
