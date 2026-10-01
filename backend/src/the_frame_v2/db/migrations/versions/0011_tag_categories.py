"""Tag categories, recently used tags, and the indexes tag inheritance walks.

`docs/organization.md` §1: a tag may belong to one **category** (People, Events, Themes… — one
level, no nesting); a NULL category is "Other". `tags.last_used_at` lets the picker offer recent
tags first. An artwork carries its photos' tags, so the tag filter walks `tag → photos → artworks`:
both link tables get an index led by `tag_id`.

The two `tags` columns are added with a plain `ALTER TABLE … ADD COLUMN`, never a batch rebuild:
`photo_tags` and `artwork_tags` cascade from `tags`, and a rebuild drops the table — with foreign
keys on, that would delete every tag link in the library.

Revision ID: 83546c17327b
Revises: 32545e54fd09
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from the_frame_v2.ids import new_id

revision: str = "83546c17327b"
down_revision: str | None = "32545e54fd09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The starting set (renamable, deletable). "Places" is deliberately absent: a place is photo
#: metadata, browsed from the Places view, never a tag (docs/organization.md §1).
DEFAULT_CATEGORIES = (("People", "#a855f7"), ("Events", "#f59e0b"), ("Themes", "#22c55e"))


def upgrade() -> None:
    op.create_table(
        "tag_categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=64, collation="NOCASE"), nullable=False),
        sa.Column("color", sa.String(length=9), nullable=True),
        sa.Column("position", sa.Float(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.execute(
        "ALTER TABLE tags ADD COLUMN category_id VARCHAR(36) "
        "REFERENCES tag_categories (id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE tags ADD COLUMN last_used_at VARCHAR(32)")
    op.create_index("ix_tags_category_id", "tags", ["category_id"], unique=False)
    op.create_index("ix_photo_tags_tag", "photo_tags", ["tag_id", "photo_id"], unique=False)
    op.create_index("ix_artwork_tags_tag", "artwork_tags", ["tag_id", "artwork_id"], unique=False)

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    categories = sa.table(
        "tag_categories",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("color", sa.String),
        sa.column("position", sa.Float),
        sa.column("created_at", sa.String),
    )
    op.bulk_insert(
        categories,
        [
            {"id": new_id(), "name": name, "color": color, "position": float(n), "created_at": now}
            for n, (name, color) in enumerate(DEFAULT_CATEGORIES, start=1)
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_artwork_tags_tag", table_name="artwork_tags")
    op.drop_index("ix_photo_tags_tag", table_name="photo_tags")
    op.drop_index("ix_tags_category_id", table_name="tags")
    op.execute("ALTER TABLE tags DROP COLUMN last_used_at")
    op.execute("ALTER TABLE tags DROP COLUMN category_id")
    op.drop_table("tag_categories")
