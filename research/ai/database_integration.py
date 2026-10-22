"""Integration tests against the Compose PostgreSQL instance, using isolated records."""
from datetime import timedelta
import unittest
from uuid import uuid4

import psycopg

from contracts import validate_evidence
from database import BankArticle, CompanyMetric, DatabaseSettings, PostgresRepository, ingest
from database_agent import DatabaseResearchAgent
from fixtures import profiles, news
from model_config import load_environment
from run import AS_OF
from test_database_agent import ClientFixture, calls
from langchain_core.messages import AIMessage


class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_environment()
        cls.admin = DatabaseSettings.from_env(admin=True)
        cls.reader = DatabaseSettings.from_env()
        cls.repository = PostgresRepository(cls.reader)
        cls.prefix = 'integration-' + uuid4().hex
        cls.company = profiles()[0].model_copy(update={'id': cls.prefix + '-company'})
        cls.other = profiles()[1].model_copy(update={'id': cls.prefix + '-other'})
        cls.news = news()[0].model_copy(update={'id': cls.prefix + '-news'})
        cls.related = cls.news.model_copy(update={'id': cls.prefix + '-related', 'title': 'zebraunique steel demand',
                                                 'text': 'zebraunique analysis of steel demand'})
        cls.future = cls.related.model_copy(update={'id': cls.prefix + '-future',
                                                   'published_at': (AS_OF + timedelta(days=1)).isoformat()})
        cls.bank = BankArticle(id=cls.prefix + '-bank', title='zebraunique sector outlook',
                              text='zebraunique steel demand may decline.', published_at=AS_OF.isoformat(),
                              source_ref='integration:bank', is_demo=True)
        cls.long_bank = BankArticle(id=cls.prefix + '-long-bank', title='Long sector outlook',
                                   text='Общий отраслевой обзор. ' * 1500 + 'longneedleunique steel demand may decline.',
                                   published_at=AS_OF.isoformat(), source_ref='integration:long-bank', is_demo=True)
        common = dict(name='Observed payment inflow',value=100.0,unit='RUB',period_start='2026-10-01T00:00:00Z',
                      period_end='2026-10-19T00:00:00Z', available_at=AS_OF.isoformat(),
                      source_ref='integration:payments',limitation='Synthetic aggregate, partial banking coverage',is_demo=True)
        cls.metric = CompanyMetric(id=cls.prefix + '-metric', company_id=cls.company.id, **common)
        cls.foreign_metric = CompanyMetric(id=cls.prefix + '-foreign', company_id=cls.other.id, **common)
        cls.future_metric = cls.metric.model_copy(update={'id': cls.prefix + '-future-metric',
                                                          'available_at': (AS_OF + timedelta(days=1)).isoformat()})
        ingest(cls.admin,companies=[cls.company,cls.other],events=[cls.news,cls.related,cls.future],articles=[cls.bank,cls.long_bank],
               metrics=[cls.metric,cls.foreign_metric,cls.future_metric],pairs=[(cls.prefix,cls.company.id,cls.news.id)])

    @classmethod
    def tearDownClass(cls):
        with cls.admin.connect() as connection:
            connection.execute('DELETE FROM analysis_pairs WHERE id = %s', (cls.prefix,))
            connection.execute('DELETE FROM company_metrics WHERE company_id IN (%s,%s)', (cls.company.id,cls.other.id))
            connection.execute('DELETE FROM company_profiles WHERE id IN (%s,%s)', (cls.company.id,cls.other.id))
            connection.execute('DELETE FROM news WHERE id IN (%s,%s,%s)', (cls.news.id,cls.related.id,cls.future.id))
            connection.execute('DELETE FROM bank_analytics WHERE id IN (%s,%s)', (cls.bank.id,cls.long_bank.id))

    def test_pair_and_profile_are_loaded_from_database(self):
        self.assertEqual(self.repository.get_pair(self.prefix), (self.company.id,self.news.id))
        self.assertEqual(self.repository.get_company_profile(self.company.id),self.company)

    def test_search_respects_publication_time_and_selected_event(self):
        results=self.repository.search_news('zebraunique',as_of=AS_OF,exclude_id=self.news.id)
        self.assertEqual([item.source_id for item in results],['news:' + self.related.id])
        with self.assertRaises(ValueError):
            self.repository.get_news(self.future.id,as_of=AS_OF)

    def test_bank_search_and_sql_injection(self):
        results=self.repository.search_bank_analytics('zebraunique',as_of=AS_OF)
        self.assertEqual([item.source_id for item in results],['bank:' + self.bank.id])
        self.repository.search_news("'; DROP TABLE news; --",as_of=AS_OF,exclude_id=self.news.id)
        self.assertEqual(self.repository.get_news(self.news.id,as_of=AS_OF).id,self.news.id)

    def test_metrics_do_not_leak_other_company_or_future(self):
        result=self.repository.get_company_metrics(self.company.id,as_of=AS_OF)
        self.assertEqual([item.source_id for item in result],[self.metric.source().source_id])

    def test_long_document_returns_matching_excerpt_instead_of_prefix(self):
        result = self.repository.search_bank_analytics('longneedleunique', as_of=AS_OF)
        self.assertEqual(len(result), 1)
        self.assertIn('longneedleunique steel demand', result[0].text)
        self.assertLessEqual(len(result[0].text), 6000)

    def test_reader_cannot_write_even_after_disabling_transaction_read_only(self):
        with self.reader.connect() as connection:
            connection.execute('SET TRANSACTION READ WRITE')
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute('DELETE FROM news WHERE id = %s', (self.news.id,))

    def test_complete_agent_uses_postgres_search_and_validated_evidence(self):
        client=ClientFixture([calls(('search_bank_analytics', {'query':'zebraunique'}), ('get_company_metrics', {})),
                              AIMessage(content='Done')])
        state=DatabaseResearchAgent(self.repository,client,as_of=AS_OF).run(self.company.id,self.news.id)
        self.assertEqual(len(state['retrieved_sources']),2)
        from contracts import Insight
        validate_evidence(Insight.model_validate(state['result']),self.company,self.news,state['retrieved_sources'])


if __name__ == '__main__':
    unittest.main()
