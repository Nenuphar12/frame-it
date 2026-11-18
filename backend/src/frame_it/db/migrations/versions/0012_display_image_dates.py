"""Display items: the date each upload carries; no more image clock.

- `display_target_items.image_date`: the `image_date` an upload was sent with. One UI Tizen 10
  shows it in a corner at every slideshow transition (`docs/research/tv-display.md` §2c), so it is
  now the artwork's own date — and an upload is reused only with the same date. Rows from before
  are NULL: their uploads go up again once, with the right date.
- `display_targets.image_clock` goes: it dated uploads in push order in case the TV sorted by
  date, and the same test showed it does not — it plays the upload order.

Both with a plain `ALTER TABLE`, **never a batch rebuild**: rebuilding `display_targets` drops it
with foreign keys on, `display_target_items` cascades from it, and every record of what this app
put on the TV goes — its uploads then count as somebody else's photos (invariant 15). The first
version of this migration did exactly that to a real library; `test_migrations` pins it.

Revision ID: 5d2c8e41a7f3
Revises: 83546c17327b
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5d2c8e41a7f3"
down_revision: str | None = "83546c17327b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE display_target_items ADD COLUMN image_date VARCHAR(19)")
    op.execute("ALTER TABLE display_targets DROP COLUMN image_clock")


def downgrade() -> None:
    op.execute("ALTER TABLE display_targets ADD COLUMN image_clock VARCHAR(32)")
    op.execute("ALTER TABLE display_target_items DROP COLUMN image_date")
