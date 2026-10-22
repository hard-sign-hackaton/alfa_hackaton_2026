import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def database_url():
    value = os.getenv('DATABASE_URL')
    if not value:
        raise ValueError('Set DATABASE_URL (postgresql+psycopg://...)')
    return value.replace('postgresql://', 'postgresql+psycopg://', 1)

def runtime_dir(module='news'):
    """Return a module-specific runtime directory, keeping the news default."""
    module = module or 'news'
    variable = module.upper() + '_RUNTIME_DIR'
    value = os.getenv(variable)
    return Path(value) if value else PROJECT_ROOT.parent / 'local_runtime' / module
