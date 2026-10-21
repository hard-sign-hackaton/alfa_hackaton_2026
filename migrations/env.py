"""Project-wide migrations with transactional adoption of the original news history."""
from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from app.shared.db.base import Base
from app.shared.db.session import get_engine
from app.modules.news import models  # Register module-owned tables in the common metadata.


def adopt_legacy_history(connection):
    tables = inspect(connection).get_table_names()
    if 'news_alembic_version' not in tables:
        return
    if 'alembic_version' in tables:
        raise RuntimeError('Both legacy and project Alembic histories exist; reconcile them before upgrading')
    revisions = connection.execute(text('SELECT version_num FROM news_alembic_version')).scalars().all()
    known = ScriptDirectory.from_config(context.config)
    for revision in revisions:
        if not revision.startswith('000') or known.get_revision(revision) is None:
            raise RuntimeError('Unknown legacy revision; migration history was not changed')
    connection.execute(text('ALTER TABLE news_alembic_version RENAME TO alembic_version'))


engine = get_engine(context.config.attributes.get('database_url'))
with engine.connect() as connection:
    with connection.begin():
        adopt_legacy_history(connection)
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
