"""Display items: the date each upload carries; no more image clock.

- `display_target_items.image_date`: the `image_date` an upload was sent with. One UI Tizen 10
  shows it in a corner at every slideshow transition (`docs/research/tv-display.md` §2c), so it is
  now the artwork's own date — and an upload is reused only with the same date. Rows from before
  are NULL: their uploads go up again once, with the right date.
- `display_targets.image_clock` goes: it dated uploads in push order in case the TV sorted by
  date, and the same test showed it does not — it plays the upload order.

Revision ID: 5d2c8e41a7f3
Revises: 83546c17327b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d2c8e41a7f3"
down_revision: str | None = "83546c17327b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("display_target_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image_date", sa.String(19), nullable=True))

    with op.batch_alter_table("display_targets", schema=None) as batch_op:
        batch_op.drop_column("image_clock")


def downgrade() -> None:
    with op.batch_alter_table("display_targets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image_clock", sa.String(32), nullable=True))

    with op.batch_alter_table("display_target_items", schema=None) as batch_op:
        batch_op.drop_column("image_date")
