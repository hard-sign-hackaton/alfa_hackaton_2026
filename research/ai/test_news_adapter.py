from datetime import timedelta
import unittest
from unittest.mock import patch

from app.modules.news.dto import NewsArticleDTO
from app.modules.news.services.search import NewsSearchService
from contracts import NewsEvent
from database import PostgresRepository
from fixtures import news
from news_repository import NewsReader
from run import AS_OF


class NewsAdapterTests(unittest.TestCase):
    def article(self):
        event = news()[0]
        return NewsArticleDTO(id='canonical-id', source_id='kommersant', publisher='Коммерсантъ',
            title=event.title, text=event.text, url=event.url, published_at=AS_OF, collected_at=AS_OF,
            date_provenance='test', extraction_method='test')

    def reader(self):
        return NewsReader('postgresql+psycopg://unused:unused@localhost/no_connection')

    def test_dto_converts_without_losing_metadata_in_agent(self):
        reader, article = self.reader(), self.article()
        with patch.object(reader.articles, 'get_article', return_value=article):
            result = reader.get_news(article.id, as_of=AS_OF)
        self.assertIsInstance(result, NewsEvent)
        self.assertEqual(result.id, article.id)
        self.assertEqual(reader.metadata[article.id]['publisher'], article.publisher)
        self.assertEqual(result.topics, [])

    def test_old_selected_ids_resolve_through_url(self):
        reader, article = self.reader(), self.article()
        with patch.object(reader.articles, 'get_article', return_value=None), patch.object(reader.articles, 'get_by_url', return_value=article):
            self.assertEqual(reader.resolve('legacy-id', article.url, as_of=AS_OF), article.id)

    def test_repository_delegates_news_and_keeps_company_storage_separate(self):
        reader = self.reader()
        repo = PostgresRepository(None, news_reader=reader)
        with patch.object(reader, 'search_news', return_value=[]) as search, patch.object(repo, '_read') as local:
            repo.search_news('сталь', as_of=AS_OF, exclude_id='selected')
        local.assert_not_called()
        self.assertEqual(search.call_args.kwargs['exclude_id'], 'selected')

    def test_search_sources_preserve_text_publisher_and_date(self):
        reader = self.reader()
        row = dict(id='related', title='Title', text='Actual excerpt', url='https://example.test/news',
                   publisher='Publisher', published_at=AS_OF.isoformat(), collected_at=AS_OF.isoformat())
        with patch.object(reader.articles, 'search_text', return_value=[row]) as search:
            source = reader.search_news('steel', as_of=AS_OF, exclude_id='primary')[0]
        self.assertEqual(source.text, 'Title\nActual excerpt')
        self.assertEqual(source.publisher, 'Publisher')
        self.assertEqual(search.call_args.kwargs['as_of'], AS_OF)

    def test_semantic_search_passes_cutoff_and_exclusion_before_limit(self):
        class Embeddings:
            profile = {'id': 'profile'}
            def encode_query(self, query): return [1.0] * 384
        from unittest.mock import Mock
        repository = Mock()
        repository.search_pg.return_value = []
        service = NewsSearchService(repository, Embeddings())
        service.search('сталь', 3, as_of=AS_OF, exclude_id='selected')
        self.assertEqual(repository.search_pg.call_args.kwargs,
                         {'as_of': AS_OF, 'exclude_id': 'selected', 'query': 'сталь'})
        for limit in (0, 101):
            with self.assertRaises(ValueError): service.search('сталь', limit)

    def test_missing_article_does_not_fall_back_to_demo_news(self):
        reader = self.reader()
        with patch.object(reader.articles, 'get_article', return_value=None):
            with self.assertRaises(ValueError): reader.get_news('missing', as_of=AS_OF)

    def test_model_receives_publication_metadata_with_analysis(self):
        from fixtures import profiles
        from agent import offline_insight
        from provider import LangChainClient
        import json
        event, company, captured = news()[0], profiles()[0], []
        def transport(payload):
            captured.append(json.loads(payload['messages'][1]['content']))
            return {'choices':[{'finish_reason':'stop','message':{'content':offline_insight(company,event).model_dump_json()}}]}
        client = LangChainClient(transport=transport)
        client.analyze(company,event,news_metadata={'publisher':'Publisher','collected_at':AS_OF.isoformat()})
        self.assertEqual(captured[0]['news_context'], {'published_at':event.published_at,'url':event.url,
                         'publisher':'Publisher','collected_at':AS_OF.isoformat()})


if __name__ == '__main__':
    unittest.main()
