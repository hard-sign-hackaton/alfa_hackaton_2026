from datetime import datetime, timezone
from sqlalchemy import select, text as sql, func, literal_column
from sqlalchemy.dialects.postgresql import insert
from .models import NewsSource, Article, IngestionRun, EmbeddingProfile, Embedding
from .dto import NewsArticleDTO, EmbeddingInput
from .identity import input_hash

EXCERPT_OPTIONS = 'MaxWords=180, MinWords=60, MaxFragments=1, StartSel="", StopSel=""'
RUSSIAN = literal_column("'russian'::regconfig")


def search_time(as_of):
    value = as_of or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('Search time requires a timezone')
    return value


def hit_columns(query):
    excerpt = (func.ts_headline(RUSSIAN, Article.text,
               func.websearch_to_tsquery(RUSSIAN, query), EXCERPT_OPTIONS)
               if query else func.substr(Article.text, 1, 5500))
    return [Article.id, Article.url, Article.title, excerpt.label('text'), Article.published_at,
            Article.collected_at, Article.details['publisher'].astext.label('publisher')]


def hit(row):
    result = dict(row._mapping)
    for key in ('published_at', 'collected_at'):
        result[key] = result[key].isoformat()
    if 'similarity' in result:
        result['similarity'] = float(result['similarity'])
    return result

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

    def get_article(self, article_id, *, as_of=None):
        with self.session() as s:
            row = s.scalar(select(Article).where(Article.id == article_id, Article.published_at <= search_time(as_of)))
            return NewsArticleDTO.model_validate(row.details) if row else None

    def get_by_url(self, url, *, as_of=None):
        with self.session() as s:
            row = s.scalar(select(Article).where(Article.url == url, Article.published_at <= search_time(as_of)))
            return NewsArticleDTO.model_validate(row.details) if row else None

    def search_text(self, query, top_k=5, *, as_of=None, exclude_id=None):
        if not query.strip() or not 1 <= top_k <= 100:
            raise ValueError('Nonempty query and top-k between 1 and 100 required')
        vector = func.to_tsvector(RUSSIAN, Article.title + ' ' + Article.text)
        terms = func.websearch_to_tsquery(RUSSIAN, query)
        statement = select(*hit_columns(query)).where(vector.op('@@')(terms), Article.published_at <= search_time(as_of))
        if exclude_id is not None:
            statement = statement.where(Article.id != exclude_id)
        with self.session() as s:
            return [hit(row) for row in s.execute(statement.order_by(func.ts_rank(vector, terms).desc(),
                    Article.published_at.desc(), Article.id).limit(top_k))]


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

    def search_pg(self, vector, profile_id, top_k, *, as_of=None, exclude_id=None, query=None):
        if not 1 <= top_k <= 100:
            raise ValueError('top-k must be between 1 and 100')
        distance = Embedding.vector.cosine_distance(vector)
        with self.session() as s:
            s.execute(sql("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
            s.execute(sql('SET LOCAL hnsw.ef_search = 64'))
            # Distance and publication metadata come from the same statement snapshot.
            statement = select(*hit_columns(query),
                (1 - distance).label('similarity')).select_from(Embedding)
            statement = statement.join(Article, Article.id == Embedding.article_id).where(
                Embedding.profile_id == profile_id, Embedding.input_hash == Article.content_hash,
                Article.published_at <= search_time(as_of))
            if exclude_id is not None:
                statement = statement.where(Article.id != exclude_id)
            rows = s.execute(statement.order_by(distance, Article.id).limit(top_k)).all()
        return [hit(row) for row in rows]

    def list_profiles(self):
        with self.session() as s:
            return [self._profile(row) for row in s.scalars(select(EmbeddingProfile).order_by(EmbeddingProfile.id))]

    @staticmethod
    def _profile(row):
        return {key: getattr(row, key) for key in ('id', 'model', 'revision', 'dimensions', 'normalized', 'preparation')}
