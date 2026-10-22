"""Read analytical chunks from the shared PostgreSQL module as cited sources."""
import os

from database import DatabaseError
from retrieval import RetrievedSource, timestamp


class BankReader:
    def __init__(self, url, *, mode='text', profile_id=None, embeddings=None):
        from app.shared.db.session import get_session_factory
        from app.modules.analytics.repositories import AnalyticsRepository, AnalyticsEmbeddingRepository
        if mode not in ('text', 'vector', 'hybrid'):
            raise ValueError('BANK_SEARCH_MODE must be text, vector or hybrid')
        session = get_session_factory(url)
        self.documents, self.vectors = AnalyticsRepository(session), AnalyticsEmbeddingRepository(session)
        self.mode, self.profile_id, self.embeddings = mode, profile_id, embeddings
        self.metadata = {}

    @classmethod
    def from_env(cls):
        url = os.environ.get('BANK_DATABASE_URL') or os.environ.get('NEWS_DATABASE_URL')
        return cls(url, mode=os.environ.get('BANK_SEARCH_MODE', 'text'),
                   profile_id=os.environ.get('BANK_EMBEDDING_PROFILE') or None) if url else None

    @staticmethod
    def _read(operation):
        from sqlalchemy.exc import SQLAlchemyError
        try:
            return operation()
        except SQLAlchemyError:
            raise DatabaseError('Bank analytics read failed') from None

    def _service(self):
        from app.modules.analytics.services.search import AnalyticsSearchService
        if self.mode != 'text' and self.embeddings is None:
            profiles = self._read(self.vectors.list_profiles)
            usable = [p for p in profiles if p['embeddings'] > 0]
            profile = next((p for p in usable if p['id'] == self.profile_id), None) if self.profile_id else (usable[0] if len(usable) == 1 else None)
            if profile is None:
                raise DatabaseError('Bank vectors missing or ambiguous; import/embed and select BANK_EMBEDDING_PROFILE')
            try:
                from app.shared.embeddings.e5 import E5Provider
                from app.modules.analytics.services.embedding import AnalyticsEmbeddingService
                service = AnalyticsEmbeddingService(self.vectors, E5Provider(revision=profile['revision']))
            except (ImportError, OSError, RuntimeError):
                raise DatabaseError('Bank embedding model unavailable') from None
            if any(service.profile[key] != profile[key] for key in service.profile):
                raise DatabaseError('Stored bank embedding profile is incompatible')
            self.embeddings = service
        return AnalyticsSearchService(self.documents, self.embeddings)

    def search(self, query, *, as_of, limit=3):
        if not 1 <= limit <= 3:
            raise ValueError('Bank context limit must be between 1 and 3')
        cutoff = timestamp(as_of)
        hits = self._read(lambda: self._service().search(query, limit, as_of=cutoff, mode=self.mode, per_document=2))
        result = []
        for row in hits:
            if timestamp(row['published_at']) > cutoff:
                raise ValueError('Future bank document rejected')
            pages = ','.join(str(p) for p in row['pages']) or 'не указаны'
            text = (f"Документ: {row['document_title']}\nДата публикации: {row['published_at']}\n"
                    f"Страницы: {pages}\nРаздел: {' > '.join(row['section_path'])}\n")
            if row.get('extraction', {}).get('mode') == 'chunks_only':
                text += 'OCR-фрагмент; полные сетки таблиц и данные графиков отсутствуют.\n'
            text = (text + '\n' + row['text'])[:6000]
            source_id = 'bank:' + row['chunk_id']
            self.metadata[source_id] = {key: row[key] for key in
                ('document_id', 'document_title', 'source_name', 'pages', 'section_path', 'published_at') if key in row}
            result.append(RetrievedSource(source_id=source_id, kind='bank', title=row['document_title'][:500],
                text=text, published_at=row['published_at'],
                locator='database:analytics_chunks/' + row['chunk_id'] + '?pages=' + pages,
                publisher='Альфа-Банк', is_demo=False))
        return result
