"""Import sessions for archives (`docs/archive-format.md` §12.2, Phase 10).

An import is received, staged and reported on before anything is written to the library, so it
needs a row of its own; the archive lives in `imports/<id>/` and is disposable.

The FTS5 `search_index*` tables autogenerate as drops (created by 0001, rebuilt on demand by
`services/search.reindex_all`): those lines are deleted by hand, as always.

Revision ID: ecaed64febed
Revises: 4d054e1a84e5
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ecaed64febed"
down_revision: str | None = "4d054e1a84e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "archive_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("received_bytes", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=128), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("archive_imports")
