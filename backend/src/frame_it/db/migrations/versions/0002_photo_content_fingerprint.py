"""photo content fingerprint and hash aliases

Revision ID: e510272408f9
Revises: bee796d06711
Create Date: 2026-09-17 11:39:53.933261
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e510272408f9"
down_revision: str | None = "bee796d06711"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photo_hash_aliases",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("photo_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["photo_id"], ["photos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("sha256"),
    )
    op.create_index("ix_photo_hash_aliases_photo_id", "photo_hash_aliases", ["photo_id"])
    # Filled for existing rows by the `fingerprint_backfill` job at startup.
    op.add_column("photos", sa.Column("content_fingerprint", sa.String(length=64), nullable=True))
    op.create_index("ux_photos_content_fingerprint", "photos", ["content_fingerprint"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_photos_content_fingerprint", table_name="photos")
    with op.batch_alter_table("photos") as batch_op:
        batch_op.drop_column("content_fingerprint")
    op.drop_index("ix_photo_hash_aliases_photo_id", table_name="photo_hash_aliases")
    op.drop_table("photo_hash_aliases")
