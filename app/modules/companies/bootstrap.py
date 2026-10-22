from app.shared.db.session import get_session_factory

from .repositories import CompanyEmbeddingRepository, CompanyRepository


def repositories(url=None):
    sessions = get_session_factory(url)
    return CompanyRepository(sessions), CompanyEmbeddingRepository(sessions)
