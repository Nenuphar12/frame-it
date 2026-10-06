"""Indexes the organization phase leans on (trash, sorts, manual collection order).

The FTS5 `search_index*` tables autogenerate as drops: they are created by 0001 and rebuilt on
demand (`services/search.reindex_all`), so they are left alone here.

Revision ID: 4d054e1a84e5
Revises: b1f0c7d24a85
Create Date: 2026-09-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4d054e1a84e5"
down_revision: str | None = "b1f0c7d24a85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("artworks", schema=None) as batch_op:
        batch_op.create_index("ix_artworks_deleted", ["deleted_at"], unique=False)
        batch_op.create_index("ix_artworks_title", ["title", "id"], unique=False)
        batch_op.create_index("ix_artworks_updated", ["updated_at", "id"], unique=False)
    with op.batch_alter_table("collection_items", schema=None) as batch_op:
        batch_op.create_index(
            "ix_collection_items_order", ["collection_id", "position"], unique=False
        )
    with op.batch_alter_table("photos", schema=None) as batch_op:
        batch_op.create_index("ix_photos_deleted", ["deleted_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("photos", schema=None) as batch_op:
        batch_op.drop_index("ix_photos_deleted")
    with op.batch_alter_table("collection_items", schema=None) as batch_op:
        batch_op.drop_index("ix_collection_items_order")
    with op.batch_alter_table("artworks", schema=None) as batch_op:
        batch_op.drop_index("ix_artworks_updated")
        batch_op.drop_index("ix_artworks_title")
        batch_op.drop_index("ix_artworks_deleted")
