from app.shared.db.session import get_session_factory
from .repositories import NewsRepository, NewsEmbeddingRepository

def repositories(url=None):
    sessions = get_session_factory(url)
    return NewsRepository(sessions), NewsEmbeddingRepository(sessions)
