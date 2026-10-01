"""Migrations that touch rows other tables cascade from (docs/data-model.md)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import text

from the_frame_v2.db.migrate import alembic_config, upgrade_to_head
from the_frame_v2.db.session import Database

BEFORE_TAG_CATEGORIES = "32545e54fd09"  # 0010, the revision 0011 builds on


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
