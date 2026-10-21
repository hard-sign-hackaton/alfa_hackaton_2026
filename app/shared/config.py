import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def database_url():
    value = os.getenv('DATABASE_URL')
    if not value:
        raise ValueError('Set DATABASE_URL (postgresql+psycopg://...)')
    return value.replace('postgresql://', 'postgresql+psycopg://', 1)

def runtime_dir():
    return Path(os.getenv('NEWS_RUNTIME_DIR', str(PROJECT_ROOT.parent / 'local_runtime' / 'news')))
