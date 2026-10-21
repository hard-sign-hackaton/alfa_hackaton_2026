from alembic import command
from alembic.config import Config
from app.shared.config import PROJECT_ROOT, database_url

def upgrade_database(url=None):
    config = Config(str(PROJECT_ROOT / 'alembic.ini'))
    config.attributes['database_url'] = url or database_url()
    command.upgrade(config, 'head')
