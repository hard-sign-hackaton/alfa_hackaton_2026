from datetime import datetime, timezone
from sqlalchemy import select, text as sql
from sqlalchemy.dialects.postgresql import insert
from .models import NewsSource, Article, IngestionRun, EmbeddingProfile, Embedding
from .dto import NewsArticleDTO, EmbeddingInput
from .identity import input_hash

class NewsRepository:
    def __init__(self, session_factory):
        self.session = session_factory

    def seed(self, sources):
        with self.session.begin() as s:
            for source in sources:
                stmt = insert(NewsSource).values(id=source.id, name=source.name, sitemap=source.sitemap, rss=source.rss)
                s.execute(stmt.on_conflict_do_update(index_elements=['id'], set_=dict(name=source.name, sitemap=source.sitemap, rss=source.rss)))

    def save(self, article):
        data = article.model_dump(mode='json')
        values = dict(id=article.id, source_id=article.source_id, url=article.url, title=article.title,
                      text=article.text, published_at=article.published_at, collected_at=article.collected_at,
                      content_hash=input_hash(article.title, article.text), details=data)
        with self.session.begin() as s:
            # Serialize same-URL updates even across CLI processes; triggers invalidate changed vectors.
            s.execute(sql('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'), {'key': article.id})
            old = s.get(Article, article.id)
            outcome = 'inserted' if old is None else 'updated' if old.content_hash != values['content_hash'] else 'unchanged'
            stmt = insert(Article).values(**values)
            s.execute(stmt.on_conflict_do_update(index_elements=['id'], set_={k: v for k, v in values.items() if k != 'id'}))
        return outcome

    def record_run(self, report):
        with self.session.begin() as s:
            s.add(IngestionRun(source_id=report['source'], started_at=datetime.fromisoformat(report['started_at']),
                               finished_at=datetime.fromisoformat(report['finished_at']), status=report['status'], report=report))

    def list_articles(self):
        with self.session() as s:
            return [NewsArticleDTO.model_validate(row.details) for row in s.scalars(
                select(Article).order_by(Article.published_at, Article.id))]


class NewsEmbeddingRepository:
    def __init__(self, session_factory):
        self.session = session_factory

    def ensure_profile(self, profile):
        with self.session.begin() as s:
            s.execute(insert(EmbeddingProfile).values(**profile).on_conflict_do_nothing(index_elements=['id']))

    def pending(self, profile_id, limit):
        with self.session() as s:
            q = select(Article).outerjoin(Embedding, (Embedding.article_id == Article.id) & (Embedding.profile_id == profile_id))
            q = q.where((Embedding.id.is_(None)) | (Embedding.input_hash != Article.content_hash)).order_by(Article.id).limit(limit)
            return [EmbeddingInput(a.id, a.title, a.text, a.content_hash) for a in s.scalars(q)]

    def save_embedding(self, article, profile_id, vector, chunk_count):
        with self.session.begin() as s:
            current = s.scalar(select(Article).where(Article.id == article.id).with_for_update())
            if current is None or current.content_hash != article.content_hash:
                return False
            stmt = insert(Embedding).values(article_id=article.id, profile_id=profile_id, input_hash=article.content_hash,
                        vector=vector, chunk_count=chunk_count, created_at=datetime.now(timezone.utc))
            s.execute(stmt.on_conflict_do_update(index_elements=['article_id', 'profile_id'],
                        set_={k: getattr(stmt.excluded, k) for k in ('vector', 'input_hash', 'chunk_count', 'created_at')}))
            return True

    def search_pg(self, vector, profile_id, top_k):
        distance = Embedding.vector.cosine_distance(vector)
        with self.session() as s:
            s.execute(sql("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
            s.execute(sql('SET LOCAL hnsw.ef_search = 64'))
            # Distance and publication metadata come from the same statement snapshot.
            rows = s.execute(select(Article.id, Article.url, Article.title,
                (1 - distance).label('similarity')).select_from(Embedding)
                .join(Article, Article.id == Embedding.article_id)
                .where(Embedding.profile_id == profile_id).order_by(distance).limit(top_k)).all()
        return [dict(id=row.id, url=row.url, title=row.title, similarity=float(row.similarity)) for row in rows]

    def list_profiles(self):
        with self.session() as s:
            return [self._profile(row) for row in s.scalars(select(EmbeddingProfile).order_by(EmbeddingProfile.id))]

    @staticmethod
    def _profile(row):
        return {key: getattr(row, key) for key in ('id', 'model', 'revision', 'dimensions', 'normalized', 'preparation')}
