"""Display targets: cached TV counts, the last push, live progress, and "Don't change" pushes.

- `display_targets` caches what the TV last said (`ours_count`, `foreign_count`, `checked_at`)
  so the UI can say "3 photos this app did not send" without a probe that takes seconds, keeps the
  last push's result and the running push's progress (a reload shows both), and an `image_clock`
  so every upload is dated after the previous ones — the TV lists newest first, whatever the
  wall clock says between two quick pushes.
- `display_target_items.position` becomes nullable: a row now means "this app uploaded it and the
  TV still holds it", and a NULL position means it is no longer part of the set. A "Don't change"
  push deletes nothing, so ours outside the set stay on the TV — and must stay in the map, or the
  next push would take them for somebody else's photos.

Revision ID: 32545e54fd09
Revises: 8a190695f690
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "32545e54fd09"
down_revision: str | None = "8a190695f690"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("display_target_items", schema=None) as batch_op:
        batch_op.alter_column("position", existing_type=sa.INTEGER(), nullable=True)

    with op.batch_alter_table("display_targets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ours_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("foreign_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("checked_at", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("last_result", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("progress", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("image_clock", sa.String(32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("display_targets", schema=None) as batch_op:
        batch_op.drop_column("image_clock")
        batch_op.drop_column("progress")
        batch_op.drop_column("last_result")
        batch_op.drop_column("checked_at")
        batch_op.drop_column("foreign_count")
        batch_op.drop_column("ours_count")

    # Rows outside the set have no position to give back: they take the end of the order.
    op.execute("UPDATE display_target_items SET position = 1000000 WHERE position IS NULL")
    with op.batch_alter_table("display_target_items", schema=None) as batch_op:
        batch_op.alter_column("position", existing_type=sa.INTEGER(), nullable=False)
