from datetime import timedelta
from unittest.mock import Mock, patch
import unittest

from app.modules.analytics.services.search import AnalyticsSearchService
from bank_repository import BankReader
from database import PostgresRepository
from run import AS_OF


def hit(key='doc#1', doc='doc', **updates):
    return dict(chunk_id=key, document_id=doc, document_title='Bank outlook', source_name='source.pdf',
        published_at=AS_OF.isoformat(), section_path=['Demand'], pages=[2], text='Demand forecast. Rate forecast.',
        extraction={'mode': 'chunks_only'}, **updates)


class BankAdapterTests(unittest.TestCase):
    def setUp(self):
        self.reader = BankReader('postgresql+psycopg://unused:unused@localhost/no_connection')

    def test_sources_have_stable_ids_page_locators_and_no_fake_public_url(self):
        service = Mock()
        service.search.return_value = [hit()]
        with patch.object(self.reader, '_service', return_value=service):
            first = self.reader.search('demand', as_of=AS_OF)
            second = self.reader.search('rate', as_of=AS_OF)
        self.assertEqual(first, second)
        self.assertEqual(first[0].source_id, 'bank:doc#1')
        self.assertIn('pages=2', first[0].locator)
        self.assertIsNone(first[0].url)
        self.assertFalse(first[0].is_demo)
        self.assertIn('OCR', first[0].text)
        self.assertEqual(self.reader.metadata['bank:doc#1']['pages'], [2])

    def test_future_document_rejected_even_if_backend_returns_it(self):
        service = Mock()
        row = hit(); row['published_at'] = (AS_OF + timedelta(days=1)).isoformat()
        service.search.return_value = [row]
        with patch.object(self.reader, '_service', return_value=service), self.assertRaises(ValueError):
            self.reader.search('demand', as_of=AS_OF)

    def test_repository_uses_new_reader_without_legacy_table(self):
        reader = Mock()
        repo = PostgresRepository(None, bank_reader=reader)
        with patch.object(repo, '_read') as legacy:
            repo.search_bank_analytics('demand', as_of=AS_OF)
        legacy.assert_not_called()
        reader.search.assert_called_once_with('demand', as_of=AS_OF, limit=3)

    def test_hybrid_fuses_rankings_and_diversifies_documents(self):
        documents, embeddings = Mock(), Mock()
        embeddings.profile = {'id': 'profile'}
        embeddings.repository.search_pg.return_value = [hit('a#1','a'), hit('a#2','a'), hit('a#3','a')]
        documents.search_text.return_value = [hit('b#1','b'), hit('a#2','a')]
        rows = AnalyticsSearchService(documents, embeddings).search('demand', 3, mode='hybrid', as_of=AS_OF)
        self.assertEqual(rows[0]['chunk_id'], 'a#2')
        self.assertEqual(len(rows), 3)
        self.assertIn('b', [r['document_id'] for r in rows])


if __name__ == '__main__': unittest.main()
