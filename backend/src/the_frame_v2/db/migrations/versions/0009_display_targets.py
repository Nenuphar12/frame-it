"""Display targets: the TVs a set can be pushed to, and what this app put on them.

Phase 12 (`docs/tv-display.md`). `display_targets` holds one TV — its address, its pairing token
(a credential, so it stays in the data dir), the set it shows and how it rotates. The Frame's
slideshow cannot be scoped to a subset (`docs/research/tv-display.md`), so a push makes the TV's
My Photos *be* the set; `display_target_items` maps `(artwork, render_hash) -> content_id` so a
re-push uploads nothing and so the app only ever deletes what it uploaded itself.

Revision ID: 8a190695f690
Revises: c1b93e77a412
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8a190695f690"
down_revision: str | None = "c1b93e77a412"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "display_targets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("host", sa.String(length=64), nullable=False),
        sa.Column("mac", sa.String(length=32), nullable=True),
        sa.Column("token", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("api_version", sa.String(length=32), nullable=True),
        sa.Column("source", sa.JSON(), nullable=True),
        sa.Column("source_label", sa.String(length=256), nullable=True),
        sa.Column("slideshow_minutes", sa.Integer(), nullable=False),
        sa.Column("slideshow_ordered", sa.Boolean(), nullable=False),
        sa.Column("render_format", sa.String(length=8), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("last_pushed_at", sa.String(32), nullable=True),
        sa.Column("last_seen_at", sa.String(32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "display_target_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("artwork_id", sa.String(length=36), nullable=False),
        sa.Column("render_hash", sa.String(length=64), nullable=False),
        sa.Column("content_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["display_targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("display_target_items", schema=None) as batch_op:
        batch_op.create_index("ix_display_items_artwork", ["target_id", "artwork_id"], unique=False)
        batch_op.create_index("ix_display_items_target", ["target_id", "position"], unique=False)
        batch_op.create_index("uq_display_items_content", ["target_id", "content_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("display_target_items", schema=None) as batch_op:
        batch_op.drop_index("uq_display_items_content")
        batch_op.drop_index("ix_display_items_target")
        batch_op.drop_index("ix_display_items_artwork")

    op.drop_table("display_target_items")
    op.drop_table("display_targets")
