"""PostgreSQL storage and bounded, parameterized read operations."""
from dataclasses import dataclass, field
import json
import os

from pydantic import Field, model_validator

from contracts import CompanyProfile, NewsEvent, StrictModel
from retrieval import RetrievedSource, timestamp

EXCERPT_OPTIONS = 'MaxWords=180, MinWords=60, MaxFragments=1, StartSel="", StopSel=""'


class DatabaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    dbname: str
    user: str
    password: str = field(repr=False)

    @classmethod
    def from_env(cls, *, admin=False):
        password = os.environ.get('POSTGRES_PASSWORD' if admin else 'DB_AGENT_PASSWORD', '')
        if not password:
            raise DatabaseError('Database password is required')
        return cls(os.environ.get('DB_HOST', 'localhost'), int(os.environ.get('DB_PORT', '55432')),
                   os.environ.get('DB_NAME', 'alfa'), 'postgres' if admin else 'analysis_agent', password)

    def connect(self):
        import psycopg
        from psycopg.rows import dict_row
        try:
            return psycopg.connect(host=self.host, port=self.port, dbname=self.dbname,
                                   user=self.user, password=self.password, connect_timeout=5,
                                   row_factory=dict_row)
        except psycopg.Error:
            raise DatabaseError('Database connection failed') from None


class CompanyMetric(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    company_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    value: float
    unit: str = Field(min_length=1, max_length=50)
    period_start: str
    period_end: str
    available_at: str
    source_ref: str = Field(min_length=1, max_length=1000)
    limitation: str = Field(min_length=1, max_length=1000)
    is_demo: bool = False

    @model_validator(mode='after')
    def period(self):
        if not timestamp(self.period_start) <= timestamp(self.period_end) <= timestamp(self.available_at):
            raise ValueError('Metric period or availability is invalid')
        return self

    def source(self):
        return RetrievedSource(source_id=f'metric:{self.company_id}:{self.id}', kind='metric',
                               title=self.name, text=self.model_dump_json(), company_id=self.company_id,
                               published_at=self.available_at, locator=self.source_ref, is_demo=self.is_demo)


class BankArticle(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=200000)
    published_at: str
    url: str | None = None
    source_ref: str = Field(min_length=1, max_length=1000)
    is_demo: bool = False

    @model_validator(mode='after')
    def publication_date(self):
        timestamp(self.published_at)
        return self


class PostgresRepository:
    def __init__(self, settings, *, news_reader=None, company_reader=None, bank_reader=None, as_of=None):
        self.settings = settings
        self.news_reader = news_reader
        self.company_reader, self.as_of = company_reader, as_of
        self.bank_reader = bank_reader

    def resolve_news_id(self, news_id, *, as_of=None):
        if self.news_reader is None:
            return news_id
        if news_id.startswith('demo:'):
            return self.news_reader.resolve(news_id, as_of=as_of)
        rows = self._read("SELECT payload->>'url' AS url FROM news WHERE id = %s", (news_id,))
        return self.news_reader.resolve(news_id, rows[0]['url'] if rows else None, as_of=as_of)

    def news_metadata(self, news_id):
        return self.news_reader.metadata.get(news_id, {}) if self.news_reader else {}

    def _read(self, query, params):
        import psycopg
        try:
            with self.settings.connect() as connection:
                connection.execute('SET TRANSACTION READ ONLY')
                connection.execute("SET LOCAL statement_timeout = '5s'")
                return connection.execute(query, params).fetchall()
        except psycopg.Error:
            raise DatabaseError('Database read failed') from None

    def get_pair(self, pair_id):
        rows = self._read('SELECT company_id, news_id FROM analysis_pairs WHERE id = %s', (pair_id,))
        if not rows:
            raise ValueError('Analysis pair not found')
        return rows[0]['company_id'], rows[0]['news_id']

    def get_company_profile(self, company_id):
        if self.company_reader is not None and not company_id.startswith('demo-'):
            return self.company_reader.get_company_profile(company_id, as_of=self.as_of)
        rows = self._read('SELECT payload FROM company_profiles WHERE id = %s', (company_id,))
        if not rows:
            raise ValueError('Company not found')
        value = CompanyProfile.model_validate(rows[0]['payload'])
        if value.id != company_id:
            raise ValueError('Company storage identity mismatch')
        return value

    def get_news(self, news_id, *, as_of):
        if self.news_reader is not None:
            return self.news_reader.get_news(news_id, as_of=as_of)
        rows = self._read('SELECT payload FROM news WHERE id = %s AND published_at <= %s',
                          (news_id, timestamp(as_of)))
        if not rows:
            raise ValueError('Publication not found or not yet published')
        value = NewsEvent.model_validate(rows[0]['payload'])
        if value.id != news_id or timestamp(value.published_at) > timestamp(as_of):
            raise ValueError('Publication storage mismatch')
        return value

    def get_company_metrics(self, company_id, *, as_of, limit=5):
        if self.company_reader is not None and not company_id.startswith('demo-'):
            return self.company_reader.get_company_metrics(company_id, as_of=as_of, limit=limit)
        rows = self._read('SELECT payload FROM company_metrics WHERE company_id = %s '
                          'AND available_at <= %s ORDER BY available_at DESC, id LIMIT %s',
                          (company_id, timestamp(as_of), min(max(limit, 1), 5)))
        values = [CompanyMetric.model_validate(row['payload']) for row in rows]
        if any(value.company_id != company_id or timestamp(value.available_at) > timestamp(as_of) for value in values):
            raise ValueError('Metric storage identity mismatch')
        return [value.source() for value in values]

    def search_news(self, query, *, as_of, exclude_id, limit=3):
        if self.news_reader is not None:
            return self.news_reader.search_news(query, as_of=as_of, exclude_id=exclude_id, limit=limit)
        rows = self._read("SELECT id, title, ts_headline('russian', text, websearch_to_tsquery('russian', %s), %s) AS text, "
                          "published_at, payload->>'url' AS url FROM news "
                          "WHERE search_vector @@ websearch_to_tsquery('russian', %s) "
                          'AND published_at <= %s AND id <> %s '
                          "ORDER BY ts_rank(search_vector, websearch_to_tsquery('russian', %s)) DESC, "
                          'published_at DESC, id LIMIT %s',
                          (query, EXCERPT_OPTIONS, query, timestamp(as_of), exclude_id, query, min(max(limit, 1), 3)))
        return [RetrievedSource(source_id='news:' + row['id'], kind='news', title=row['title'][:500],
                                text=(row['title'] + '\n' + row['text'])[:6000],
                                published_at=row['published_at'].isoformat(), url=row['url'],
                                locator=row['url'] or 'database:news/' + row['id']) for row in rows]

    def search_bank_analytics(self, query, *, as_of, limit=3):
        if self.bank_reader is not None:
            return self.bank_reader.search(query, as_of=as_of, limit=limit)
        rows = self._read("SELECT id, title, ts_headline('russian', text, websearch_to_tsquery('russian', %s), %s) AS text, "
                          "published_at, url, source_ref, is_demo FROM bank_analytics "
                          "WHERE search_vector @@ websearch_to_tsquery('russian', %s) AND published_at <= %s "
                          "ORDER BY ts_rank(search_vector, websearch_to_tsquery('russian', %s)) DESC, "
                          'published_at DESC, id LIMIT %s',
                          (query, EXCERPT_OPTIONS, query, timestamp(as_of), query, min(max(limit, 1), 3)))
        return [RetrievedSource(source_id='bank:' + row['id'], kind='bank', title=row['title'],
                                text=(row['title'] + '\n' + row['text'])[:6000],
                                published_at=row['published_at'].isoformat(), url=row['url'],
                                locator=row['source_ref'], is_demo=row['is_demo']) for row in rows]


def ingest(settings, *, companies=(), events=(), articles=(), metrics=(), pairs=()):
    """Import validated records with a separate writer connection; no model access."""
    from psycopg.types.json import Jsonb
    companies = [CompanyProfile.model_validate(item) for item in companies]
    events = [NewsEvent.model_validate(item) for item in events]
    articles = [BankArticle.model_validate(item) for item in articles]
    metrics = [CompanyMetric.model_validate(item) for item in metrics]
    for event in events:
        timestamp(event.published_at)
    with settings.connect() as connection:
        connection.execute('ALTER TABLE analysis_pairs DROP CONSTRAINT IF EXISTS analysis_pairs_news_id_fkey')
        for company in companies:
            connection.execute('INSERT INTO company_profiles (id, payload) VALUES (%s, %s) '
                               'ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload',
                               (company.id, Jsonb(company.model_dump())))
        for event in events:
            connection.execute('INSERT INTO news (id, title, text, published_at, payload) VALUES (%s,%s,%s,%s,%s) '
                               'ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title, text=EXCLUDED.text, '
                               'published_at=EXCLUDED.published_at, payload=EXCLUDED.payload',
                               (event.id, event.title, event.text, timestamp(event.published_at), Jsonb(event.model_dump())))
        for article in articles:
            connection.execute('INSERT INTO bank_analytics (id,title,text,published_at,url,source_ref,is_demo) '
                               'VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET '
                               'title=EXCLUDED.title,text=EXCLUDED.text,published_at=EXCLUDED.published_at,'
                               'url=EXCLUDED.url,source_ref=EXCLUDED.source_ref,is_demo=EXCLUDED.is_demo',
                               (article.id,article.title,article.text,timestamp(article.published_at),
                                article.url,article.source_ref,article.is_demo))
        for metric in metrics:
            connection.execute('INSERT INTO company_metrics (id,company_id,available_at,payload) VALUES (%s,%s,%s,%s) '
                               'ON CONFLICT (company_id,id) DO UPDATE SET available_at=EXCLUDED.available_at,payload=EXCLUDED.payload',
                               (metric.id,metric.company_id,timestamp(metric.available_at),Jsonb(metric.model_dump())))
        for pair_id, company_id, news_id in pairs:
            connection.execute('INSERT INTO analysis_pairs (id,company_id,news_id) VALUES (%s,%s,%s) '
                               'ON CONFLICT (id) DO UPDATE SET company_id=EXCLUDED.company_id,news_id=EXCLUDED.news_id',
                               (pair_id,company_id,news_id))
    return {'companies': len(companies), 'news': len(events), 'bank_articles': len(articles), 'metrics': len(metrics), 'pairs': len(pairs)}


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    from model_config import load_environment
    parser = argparse.ArgumentParser(description='Load demo records or a validated JSON dataset into PostgreSQL.')
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--seed-demo', action='store_true')
    choice.add_argument('--import-json', type=Path, help='Object with companies, news, bank_analytics and company_metrics arrays')
    args = parser.parse_args()
    load_environment()
    if args.seed_demo:
        from fixtures import profiles, news
        companies, events = profiles(), news()
        if os.environ.get('NEWS_SEED_DATABASE_URL'):
            from app.modules.news.dto import NewsArticleDTO
            from app.modules.news.identity import article_id
            from app.modules.news.bootstrap import repositories
            from app.modules.news.parsers.registry import SOURCES
            from datetime import datetime, timezone
            from urllib.parse import urlparse
            repository, _ = repositories(os.environ['NEWS_SEED_DATABASE_URL'])
            repository.seed([value.source for value in SOURCES.values()])
            canonical_events = []
            for event in events:
                source = next(value.source for value in SOURCES.values() if urlparse(event.url).hostname.removeprefix('www.') == value.source.host)
                article = NewsArticleDTO(id=article_id(event.url), source_id=source.id, publisher=source.name,
                    title=event.title, text=event.text, url=event.url, published_at=timestamp(event.published_at),
                    collected_at=datetime.now(timezone.utc), date_provenance='saved_publication', extraction_method='imported_saved_text')
                repository.save(article)
                canonical_events.append(event.model_copy(update={'id': article.id}))
            events = canonical_events
        result = ingest(DatabaseSettings.from_env(admin=True), companies=companies, events=events,
                        pairs=[(company.id + '-primary',company.id,events[0].id) for company in companies])
    else:
        data = json.loads(args.import_json.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) - {'companies','news','bank_analytics','company_metrics'}:
            parser.error('Unknown dataset fields')
        result = ingest(DatabaseSettings.from_env(admin=True), companies=data.get('companies', []),
                        events=data.get('news', []), articles=data.get('bank_analytics', []), metrics=data.get('company_metrics', []))
    print(json.dumps(result))
