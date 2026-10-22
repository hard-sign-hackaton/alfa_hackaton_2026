"""Opt-in destructive tests, allowed only on an explicitly named *_test database."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import unittest
import uuid
import numpy as np
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.modules.news.dto import NewsArticleDTO as IngestedNews
from app.modules.news.identity import article_id
from app.shared.db.session import get_session_factory
from app.modules.news.repositories import NewsRepository, NewsEmbeddingRepository
from app.modules.news.models import Article, Embedding, EmbeddingProfile
from app.shared.embeddings.provider import normalize
from app.modules.news.services.embedding import NewsEmbeddingService
from app.modules.news.services.search import NewsSearchService
from app.modules.news.parsers.registry import SOURCES
from app.shared.db.migrations import upgrade_database
from app.modules.news.dto import EmbeddingInput, NewsArticleDTO

URL = os.getenv('NEWS_TEST_DATABASE_URL')
ROOT = Path(__file__).resolve().parents[2]


def migration_head():
    config = Config()
    config.set_main_option('script_location', str(ROOT / 'migrations'))
    return ScriptDirectory.from_config(config).get_current_head()


@unittest.skipUnless(URL, 'Set NEWS_TEST_DATABASE_URL to a disposable *_test database')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not make_url(URL).database.endswith('_test'):
            raise ValueError('Integration tests require a dedicated *_test database')
        cls.sessions = get_session_factory(URL)
        cls.repo = NewsRepository(cls.sessions)
        cls.vectors = NewsEmbeddingRepository(cls.sessions)
        cls.repo.seed([s.source for s in SOURCES.values()])

    def setUp(self):
        self.token = uuid.uuid4().hex
        self.ids = []
        self.profile_id = hashlib.sha256(self.token.encode()).hexdigest()

    def tearDown(self):
        with self.repo.session.begin() as s:
            s.execute(delete(Article).where(Article.id.in_(self.ids)))
            s.execute(delete(EmbeddingProfile).where(EmbeddingProfile.id == self.profile_id))

    def article(self, suffix='one'):
        url = 'https://www.kommersant.ru/doc/' + self.token + suffix
        record = IngestedNews(id=article_id(url), source_id='kommersant', publisher='Коммерсантъ', url=url,
                    title='Integration fixture ' + suffix, text='Explicitly synthetic test fixture, not a real publication. ' * 8,
                    published_at=datetime.now(timezone.utc), collected_at=datetime.now(timezone.utc),
                    date_provenance='test_fixture', extraction_method='test_fixture')
        self.ids.append(record.id)
        return record

    def provider(self):
        class Provider(NewsEmbeddingService):
            profile = dict(id=self.profile_id, model='test-only', revision='test-only', dimensions=384,
                           normalized=True, preparation='test-only')
            calls = 0
            def encode_articles(inner, articles, batch_size=32):
                inner.calls += 1
                return [(normalize(np.arange(384, dtype=np.float32) + 1), 1) for a in articles]
            def encode_query(inner, query):
                return normalize(np.arange(384, dtype=np.float32) + 1)
        return Provider(self.vectors, None)

    def test_upsert_invalidation_and_search(self):
        article = self.article()
        self.assertEqual(self.repo.save(article), 'inserted')
        self.assertEqual(self.repo.save(article), 'unchanged')
        provider = self.provider()
        self.assertEqual(provider.run()['saved'], 1)
        self.assertEqual(provider.run()['saved'], 0)
        self.assertEqual(provider.calls, 1)
        service = NewsSearchService(self.vectors, provider)
        result = service.search('fixture', 5)
        self.assertEqual(result[0]['id'], article.id)
        self.assertAlmostEqual(result[0]['similarity'], 1, places=5)
        changed = article.model_copy(update={'text': article.text + ' Update.'})
        self.assertEqual(self.repo.save(changed), 'updated')
        with self.repo.session() as s:
            self.assertIsNone(s.scalar(select(Embedding).where(Embedding.article_id == article.id)))
        self.assertEqual(service.search('fixture'), [])
        self.assertEqual(provider.run()['saved'], 1)
        self.assertEqual(len(service.search('fixture')), 1)

    def test_changed_input_cannot_save_old_embedding(self):
        article = self.article()
        self.repo.save(article)
        provider = self.provider()
        self.vectors.ensure_profile(provider.profile)
        old = self.vectors.pending(self.profile_id, 1)[0]
        self.repo.save(article.model_copy(update={'title': 'Changed title'}))
        self.assertFalse(self.vectors.save_embedding(old, self.profile_id, normalize(np.ones(384)), 1))

    def test_new_vectors_are_searchable_without_rebuild(self):
        provider = self.provider()
        self.vectors.ensure_profile(provider.profile)
        service = NewsSearchService(self.vectors, provider)
        self.assertEqual(service.search('fixture'), [])
        article = self.article()
        self.repo.save(article)
        self.assertEqual(service.search('fixture'), [])
        provider.run()
        self.assertEqual(service.search('fixture')[0]['id'], article.id)
        with self.sessions.begin() as s:
            s.execute(delete(Article).where(Article.id == article.id))
        self.assertEqual(service.search('fixture'), [])

    def test_search_isolates_embedding_profiles_and_validates_limit(self):
        article = self.article()
        self.repo.save(article)
        provider = self.provider()
        provider.run()
        foreign_profile = dict(provider.profile, id=hashlib.sha256((self.token+'other').encode()).hexdigest())
        self.vectors.ensure_profile(foreign_profile)
        try:
            self.assertEqual(self.vectors.search_pg(normalize(np.ones(384)), foreign_profile['id'], 5), [])
            with self.assertRaises(ValueError):
                NewsSearchService(self.vectors, provider).search('fixture', 0)
        finally:
            with self.sessions.begin() as s:
                s.execute(delete(EmbeddingProfile).where(EmbeddingProfile.id == foreign_profile['id']))

    def test_repository_returns_detached_dtos(self):
        article = self.article()
        self.repo.save(article)
        provider = self.provider()
        self.vectors.ensure_profile(provider.profile)
        self.assertIsInstance(self.vectors.pending(self.profile_id, 1)[0], EmbeddingInput)
        self.assertIsInstance(self.repo.list_articles()[0], NewsArticleDTO)

    def test_title_match_precedes_repeated_body_mentions(self):
        # The isolated token avoids depending on other test/corpus records.
        term = 'scope' + self.token
        title = self.article('title').model_copy(update={'title': term + ' в заголовке'})
        body = self.article('body').model_copy(update={'text': (term + ' ') * 80})
        self.repo.save(title)
        self.repo.save(body)
        found = self.repo.search_text(term, 2)
        self.assertEqual([row['id'] for row in found], [title.id, body.id])
        self.assertTrue(found[0]['title_match'])
        self.assertFalse(found[1]['title_match'])

    def test_legacy_history_adopted_without_losing_rows(self):
        article = self.article()
        self.repo.save(article)
        with self.sessions.begin() as s:
            s.execute(text('ALTER TABLE alembic_version RENAME TO news_alembic_version'))
        try:
            upgrade_database(URL)
            upgrade_database(URL)
            self.assertEqual(self.repo.save(article), 'unchanged')
            with self.sessions() as s:
                self.assertEqual(s.execute(text('SELECT version_num FROM alembic_version')).scalar_one(), migration_head())
                self.assertIsNone(s.execute(text("SELECT to_regclass('news_alembic_version')")).scalar_one())
        finally:
            with self.sessions.begin() as s:
                if s.execute(text("SELECT to_regclass('news_alembic_version')")).scalar_one() is not None:
                    s.execute(text('ALTER TABLE news_alembic_version RENAME TO alembic_version'))

    def test_conflicting_histories_are_not_silently_merged(self):
        with self.sessions.begin() as s:
            s.execute(text('CREATE TABLE news_alembic_version AS SELECT * FROM alembic_version'))
        try:
            with self.assertRaisesRegex(RuntimeError, 'Both legacy'):
                upgrade_database(URL)
        finally:
            with self.sessions.begin() as s:
                s.execute(text('DROP TABLE news_alembic_version'))


if __name__ == '__main__':
    unittest.main()
