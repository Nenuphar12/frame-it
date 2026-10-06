"""Alembic environment. The connection is always supplied programmatically (see db/migrate.py)."""

from alembic import context

from frame_it.db.models import Base

connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
