from functools import lru_cache
import atexit
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.shared.config import database_url

_created_engines = []

@lru_cache(maxsize=8)
def _engine(url):
    engine = create_engine(url, pool_pre_ping=True)
    _created_engines.append(engine)
    return engine

@lru_cache(maxsize=8)
def _sessions(url):
    return sessionmaker(_engine(url), expire_on_commit=False)

def get_engine(url=None):
    return _engine(url or database_url())

def get_session_factory(url=None):
    """Share an Engine/pool per URL/process, never a mutable Session between workers."""
    return _sessions(url or database_url())


@atexit.register
def dispose_engines():
    """Release pooled connections on normal interpreter shutdown."""
    for engine in _created_engines:
        engine.dispose()
    _created_engines.clear()
    _sessions.cache_clear()
    _engine.cache_clear()
