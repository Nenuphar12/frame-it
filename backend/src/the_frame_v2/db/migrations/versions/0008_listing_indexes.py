"""Listing indexes: `deleted_at` leads every artwork order.

Each grid query is "not trashed, then ordered, then a page". With `deleted_at` only in a
single-column index, SQLite read the matching rows and sorted them in a temp B-tree — on a 10k
library that is 13 ms per page of the grid and 64 ms for the oldest-first order. Leading each
composite with `deleted_at` lets the index supply the order: 0.5 ms, no sort. The composites also
answer `deleted_at IS NOT NULL` (the trash) and the `collection_items` join, so the single-column
`ix_artworks_deleted` is dropped rather than kept alongside them.

Revision ID: c1b93e77a412
Revises: 0a08bfd8cda4
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1b93e77a412"
down_revision: str | None = "0a08bfd8cda4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    ("ix_artworks_created", ["created_at", "id"]),
    ("ix_artworks_updated", ["updated_at", "id"]),
    ("ix_artworks_title", ["title", "id"]),
)
NEW = (
    ("ix_artworks_created", ["deleted_at", "created_at", "id"]),
    ("ix_artworks_updated", ["deleted_at", "updated_at", "id"]),
    ("ix_artworks_title", ["deleted_at", "title", "id"]),
    ("ix_artworks_favorite", ["deleted_at", "favorite", "created_at", "id"]),
)


def upgrade() -> None:
    with op.batch_alter_table("artworks", schema=None) as batch_op:
        for name, _ in OLD:
            batch_op.drop_index(name)
        batch_op.drop_index("ix_artworks_deleted")
        for name, columns in NEW:
            batch_op.create_index(name, columns, unique=False)


def downgrade() -> None:
    with op.batch_alter_table("artworks", schema=None) as batch_op:
        for name, _ in NEW:
            batch_op.drop_index(name)
        for name, columns in OLD:
            batch_op.create_index(name, columns, unique=False)
        batch_op.create_index("ix_artworks_deleted", ["deleted_at"], unique=False)
