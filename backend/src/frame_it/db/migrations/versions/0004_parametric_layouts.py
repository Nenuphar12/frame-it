"""parametric layouts

A layout is a recipe and its parameters since Phase 8 (docs/templates.md §2), so every stored
layout document has the wrong shape: the rows are dropped and the built-ins are re-seeded at
startup. Artworks keep their look — templates are copied on apply — but their `origin_layout_id`
would point at a layout that no longer exists and light up a bogus "outdated" badge, so the link
is cleared. `artwork_defaults` moves from {style_id, layout_id} to {style_id, recipe_id, format};
the row is deleted and rebuilt from the defaults on the next read.

Revision ID: b1f0c7d24a85
Revises: 7c2f4a1d9b30
Create Date: 2026-09-23 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1f0c7d24a85"
down_revision: str | None = "7c2f4a1d9b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM layouts"))
    op.execute(
        sa.text("UPDATE artworks SET origin_layout_id = NULL, origin_layout_revision = NULL")
    )
    op.execute(sa.text("DELETE FROM settings WHERE key = 'artwork_defaults'"))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM layouts"))
    op.execute(sa.text("DELETE FROM settings WHERE key = 'artwork_defaults'"))
