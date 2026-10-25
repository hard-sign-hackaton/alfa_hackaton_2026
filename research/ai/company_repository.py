"""Read company profiles, prepared payment aggregates and company-vector candidates."""
from datetime import datetime, timezone
import os

from contracts import CompanyProfile
from database import DatabaseError
from dataset import payment_sources
from retrieval import timestamp


class CompanyReader:
    def __init__(self, url, *, profile_id=None, embeddings=None):
        from app.shared.db.session import get_session_factory
        from app.modules.companies.repositories import CompanyEmbeddingRepository
        self.session = get_session_factory(url)
        self.vectors = CompanyEmbeddingRepository(self.session)
        self.profile_id, self.embeddings = profile_id, embeddings
        self.metadata = {}

    @classmethod
    def from_env(cls):
        url = os.environ.get('COMPANY_DATABASE_URL') or os.environ.get('NEWS_DATABASE_URL')
        return cls(url, profile_id=os.environ.get('COMPANY_EMBEDDING_PROFILE') or None) if url else None

    @staticmethod
    def _read(operation):
        from sqlalchemy.exc import SQLAlchemyError
        try:
            return operation()
        except SQLAlchemyError:
            raise DatabaseError('Company database read failed') from None

    def _snapshot(self, company_id, as_of=None):
        from sqlalchemy import select
        from app.modules.companies.models import Company
        from app.modules.companies.dto import CompanyRecord
        cutoff = timestamp(as_of) if as_of is not None else datetime.now(timezone.utc)
        def operation():
            with self.session() as session:
                row = session.scalar(select(Company).where(Company.id == company_id, Company.imported_at <= cutoff))
                if row is None:
                    raise ValueError('Company snapshot not found before as_of')
                return CompanyRecord.model_validate(row.details), row.imported_at
        record, imported_at = self._read(operation)
        if record.company_id != company_id:
            raise ValueError('Company storage identity mismatch')
        self.metadata[company_id] = {'imported_at': imported_at.isoformat(),
            'limitation': 'Current snapshot only; no historical company versions. Payment period is unknown.'}
        return record, imported_at

    def get_company_profile(self, company_id, *, as_of=None):
        from app.modules.companies.services.export import CompanyExportService
        record, _ = self._snapshot(company_id, as_of)
        return CompanyProfile.model_validate(CompanyExportService.ai_profile(record))

    def get_company_metrics(self, company_id, *, as_of, limit=5):
        record, imported_at = self._snapshot(company_id, as_of)
        return payment_sources(company_id, record.payments.model_dump(mode='json'), available_at=imported_at,
                               locator_prefix='database:companies/' + company_id)[:min(max(limit, 1), 5)]

    def _semantic(self):
        from app.modules.companies.services.embedding import CompanyEmbeddingService
        from app.modules.companies.services.search import CompanySearchService
        if self.embeddings is None:
            profiles = self._read(self.vectors.list_profiles)
            profile = next((p for p in profiles if p['id'] == self.profile_id), None) if self.profile_id else (profiles[0] if len(profiles) == 1 else None)
            if profile is None:
                raise DatabaseError('Select one existing COMPANY_EMBEDDING_PROFILE; the agent does not generate stored vectors')
            from app.shared.embeddings.e5 import E5Provider
            try:
                service = CompanyEmbeddingService(self.vectors, E5Provider(revision=profile['revision']))
            except (ImportError, RuntimeError, OSError):
                raise DatabaseError('Company embedding model is unavailable') from None
            if service.profile != profile:
                raise DatabaseError('Stored company embedding profile is incompatible')
            self.embeddings = service
        return CompanySearchService(self.vectors, self.embeddings)

    def match_news(self, news, *, as_of, limit=10):
        from types import SimpleNamespace
        from ranking import industry_topics
        cutoff = timestamp(as_of)
        if not 1 <= limit <= 100:
            raise ValueError('Candidate limit must be between 1 and 100')
        if timestamp(news.published_at) > cutoff:
            raise ValueError('Future publication cannot be matched')
        if 'not_business' in news.topics:
            return {'news_id': news.id, 'candidates': [], 'requires_impact_analysis': True,
                    'limitation': 'Publication classified as not_business; no company candidates selected.'}
        pool = min(100, max(20, limit * 5)) if news.topics else limit
        rows = self._read(lambda: self._semantic().search(news.title + '\n' + news.text[:1800], pool, as_of=cutoff))
        for row in rows:
            activity = SimpleNamespace(okved_codes=[row.get('okved_code') or ''])
            row['matched_topics'] = sorted(industry_topics(activity).intersection(news.topics))
        # An explicit dataset identifier is a stronger identity signal than thematic proximity.
        # Keep the actual embedding score; no importance or impact level is inferred here.
        import re
        text = news.title + '\n' + news.text
        mentioned = [row for row in rows if re.search(r'(?<!\w)' + re.escape(row['id']) + r'(?!\w)', text)]
        if mentioned:
            rows = mentioned
        rows.sort(key=lambda row: (not bool(row['matched_topics']), -row['similarity'], row['id']))
        return {'news_id': news.id, 'candidates': rows[:limit], 'requires_impact_analysis': True,
                'topics_used': news.topics, 'candidate_pool_limit': pool,
                'limitation': 'Similarity orders candidates; it is not a probability of impact or a measure of news importance.'}
