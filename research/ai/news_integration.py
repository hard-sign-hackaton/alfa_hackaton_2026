"""Cross-module tests using the disposable news database and scoped company records."""
from datetime import datetime, timedelta, timezone
import os
import unittest
from uuid import uuid4

import numpy as np
import psycopg
from sqlalchemy import delete

from app.modules.news.bootstrap import repositories
from app.modules.news.dto import NewsArticleDTO, EmbeddingInput
from app.modules.news.identity import article_id
from app.modules.news.models import Article, EmbeddingProfile
from app.modules.news.parsers.registry import SOURCES
from app.modules.news.services.search import NewsSearchService
from app.shared.embeddings.provider import normalize
from contracts import Insight, validate_evidence
from database import DatabaseSettings, PostgresRepository, ingest
from database_agent import DatabaseResearchAgent
from fixtures import profiles
from news_repository import NewsReader
from test_database_agent import ClientFixture, calls
from langchain_core.messages import AIMessage


class SharedNewsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix = 'bridge-' + uuid4().hex
        cls.cutoff = datetime.now(timezone.utc)
        cls.repository, cls.vectors = repositories(os.environ['NEWS_INTEGRATION_ADMIN_URL'])
        cls.repository.seed([value.source for value in SOURCES.values()])
        cls.articles = []
        for suffix, date in [('primary', cls.cutoff-timedelta(hours=2)), ('related', cls.cutoff-timedelta(hours=1)),
                             ('future', cls.cutoff+timedelta(days=1))]:
            url = 'https://www.kommersant.ru/doc/' + cls.prefix + suffix
            article = NewsArticleDTO(id=article_id(url), source_id='kommersant', publisher='Synthetic fixture',
                title='bridgeunique steel demand ' + suffix, text='Synthetic bridgeunique steel demand analysis. ' * 10,
                url=url, published_at=date, collected_at=cls.cutoff, date_provenance='test_fixture', extraction_method='test_fixture')
            cls.repository.save(article); cls.articles.append(article)
        cls.primary, cls.related, cls.future = cls.articles
        cls.company = profiles()[0].model_copy(update={'id': cls.prefix})
        cls.admin = DatabaseSettings.from_env(admin=True)
        legacy = __import__('contracts').NewsEvent.model_validate(cls.primary.ai_event()).model_copy(update={'id': cls.prefix + '-legacy'})
        cls.legacy_id = legacy.id
        ingest(cls.admin, companies=[cls.company], events=[legacy], pairs=[(cls.prefix, cls.company.id, legacy.id)])
        cls.reader = NewsReader(os.environ['NEWS_DATABASE_URL'])
        cls.agent_repository = PostgresRepository(DatabaseSettings.from_env(), news_reader=cls.reader)
        cls.profile_id = uuid4().hex
        profile = dict(id=cls.profile_id,model='synthetic-integration-vector',revision='fixture',dimensions=384,
                       normalized=True,preparation='fixture')
        cls.vectors.ensure_profile(profile)
        for article in cls.articles:
            from app.modules.news.identity import input_hash
            cls.vectors.save_embedding(EmbeddingInput(article.id,article.title,article.text,input_hash(article.title,article.text)),
                                      cls.profile_id, normalize(np.ones(384)), 1)

    @classmethod
    def tearDownClass(cls):
        with cls.repository.session.begin() as session:
            session.execute(delete(Article).where(Article.id.in_([article.id for article in cls.articles])))
            session.execute(delete(EmbeddingProfile).where(EmbeddingProfile.id == cls.profile_id))
        with cls.admin.connect() as connection:
            connection.execute('DELETE FROM analysis_pairs WHERE id=%s', (cls.prefix,))
            connection.execute('DELETE FROM company_profiles WHERE id=%s', (cls.company.id,))
            connection.execute('DELETE FROM news WHERE id=%s', (cls.legacy_id,))

    def test_legacy_pair_resolves_to_canonical_news_id(self):
        company_id, news_id = self.agent_repository.get_pair(self.prefix)
        state = DatabaseResearchAgent(self.agent_repository, ClientFixture([AIMessage(content='Done')]),
                    as_of=self.cutoff).run(company_id,news_id)
        self.assertEqual(state['news_id'],self.primary.id)
        self.assertEqual(state['news_metadata']['publisher'],'Synthetic fixture')

    def test_keyword_search_has_text_and_excludes_future_and_selected_before_limit(self):
        results = self.reader.search_news('bridgeunique', as_of=self.cutoff, exclude_id=self.primary.id, limit=1)
        self.assertEqual([source.source_id for source in results], ['news:' + self.related.id])
        self.assertIn('Synthetic bridgeunique', results[0].text)

    def test_vector_search_uses_same_filters_and_returns_evidence(self):
        class Embeddings:
            profile = {'id': self.profile_id}
            def encode_query(self, query): return normalize(np.ones(384))
        reader = NewsReader(os.environ['NEWS_DATABASE_URL'], mode='semantic', embeddings=Embeddings())
        result = reader.search_news('bridgeunique',as_of=self.cutoff,exclude_id=self.primary.id,limit=1)
        self.assertEqual([source.source_id for source in result],['news:' + self.related.id])
        self.assertEqual(result[0].publisher,'Synthetic fixture')

    def test_read_role_cannot_write_news(self):
        from app.shared.db.session import get_engine
        from sqlalchemy.exc import ProgrammingError
        from sqlalchemy import text
        with get_engine(os.environ['NEWS_DATABASE_URL']).begin() as connection:
            connection.execute(text('SET TRANSACTION READ WRITE'))
            with self.assertRaises(ProgrammingError):
                connection.execute(delete(Article).where(Article.id == self.primary.id))

    def test_real_repository_tool_result_is_citable_in_agent_analysis(self):
        client = ClientFixture([calls(('search_news',{'query':'bridgeunique'})),AIMessage(content='Done')])
        state = DatabaseResearchAgent(self.agent_repository,client,as_of=self.cutoff).run(self.company.id,self.primary.id)
        self.assertEqual(state['retrieved_sources'][0]['source_id'],'news:' + self.related.id)
        validate_evidence(Insight.model_validate(state['result']),self.company,
                         __import__('contracts').NewsEvent.model_validate(self.primary.ai_event()),state['retrieved_sources'])


if __name__ == '__main__':
    unittest.main()
