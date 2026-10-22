from app.shared.db.session import get_session_factory

from .repositories import AnalyticsEmbeddingRepository, AnalyticsRepository


def repositories(url=None):
    sessions = get_session_factory(url)
    return AnalyticsRepository(sessions), AnalyticsEmbeddingRepository(sessions)
