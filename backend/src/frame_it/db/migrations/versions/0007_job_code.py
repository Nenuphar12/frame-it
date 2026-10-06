"""Job problem code + an index for the activity centre's listing.

`jobs.code` holds the stable problem code a handler raised (`PermanentJobError`), so a client can
translate the failure instead of parsing it back out of the error text. `ix_jobs_recent` serves the
"most recent jobs in these states" query the activity centre runs.

Revision ID: 0a08bfd8cda4
Revises: ecaed64febed
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0a08bfd8cda4"
down_revision: str | None = "ecaed64febed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("code", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_jobs_recent", ["state", "created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_jobs_recent")
        batch_op.drop_column("code")
