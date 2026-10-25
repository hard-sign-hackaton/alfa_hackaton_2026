"""Company storage boundaries used by the research agent."""
from datetime import timedelta
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from app.modules.companies.dto import CompanyRecord
from company_repository import CompanyReader
from contracts import CompanyProfile
from database import PostgresRepository
from dataset import CompanyDataset
from fixtures import news
from run import AS_OF


class CompanyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.reader = CompanyReader('postgresql+psycopg://unused:unused@localhost/no_connection')
        self.dataset = CompanyDataset(Path(__file__).resolve().parents[2] / 'docs/companies/companies_analytics.json')
        self.company_id = next(iter(self.dataset.rows))
        self.record = CompanyRecord.model_validate(self.dataset.rows[self.company_id])

    def test_exported_profile_and_payment_sources_preserve_company_scope(self):
        with patch.object(self.reader, '_snapshot', return_value=(self.record, AS_OF)):
            profile = self.reader.get_company_profile(self.company_id, as_of=AS_OF)
            sources = self.reader.get_company_metrics(self.company_id, as_of=AS_OF)
        self.assertIsInstance(profile, CompanyProfile)
        self.assertIn('credit', profile.banking_services)
        self.assertIsNone(profile.trade_countries)
        self.assertEqual(len(sources), 5)
        self.assertTrue(all(source.company_id == self.company_id for source in sources))
        self.assertTrue(all(source.published_at == AS_OF.isoformat() for source in sources))
        self.assertTrue(all('неизвестный период' in source.text for source in sources))

    def test_database_repository_routes_dataset_companies_without_legacy_lookup(self):
        reader = Mock()
        repo = PostgresRepository(None, company_reader=reader, as_of=AS_OF)
        with patch.object(repo, '_read') as legacy:
            repo.get_company_profile(self.company_id)
            repo.get_company_metrics(self.company_id, as_of=AS_OF)
        legacy.assert_not_called()
        reader.get_company_profile.assert_called_once_with(self.company_id, as_of=AS_OF)

    def test_unknown_shared_company_never_falls_back_to_demo(self):
        reader = Mock()
        reader.get_company_profile.side_effect = ValueError('not found')
        repo = PostgresRepository(None, company_reader=reader)
        with patch.object(repo, '_read') as legacy, self.assertRaises(ValueError):
            repo.get_company_profile('unknown')
        legacy.assert_not_called()

    def test_reverse_search_passes_cutoff_and_cannot_accept_future_news(self):
        service = Mock()
        service.search.return_value = [{'id': self.company_id, 'similarity': .8}]
        with patch.object(self.reader, '_semantic', return_value=service):
            result = self.reader.match_news(news()[0], as_of=AS_OF)
        self.assertTrue(result['requires_impact_analysis'])
        self.assertEqual(service.search.call_args.kwargs['as_of'], AS_OF)
        with self.assertRaises(ValueError):
            self.reader.match_news(news()[0].model_copy(update={'published_at': (AS_OF + timedelta(days=1)).isoformat()}), as_of=AS_OF)

    def test_reverse_search_reranks_broader_vector_pool_by_industry_topic(self):
        service = Mock()
        service.search.return_value = [
            {'id': 'logistics', 'okved_code': '52.29', 'similarity': .85},
            {'id': 'autoparts', 'okved_code': '45.31', 'similarity': .80},
        ]
        event = news()[0].model_copy(update={'topics': ['automotive']})
        with patch.object(self.reader, '_semantic', return_value=service):
            result = self.reader.match_news(event, as_of=AS_OF, limit=1)
        self.assertGreater(service.search.call_args.args[1], 1)
        self.assertEqual(result['candidates'][0]['id'], 'autoparts')
        self.assertEqual(result['candidates'][0]['matched_topics'], ['automotive'])
        self.assertEqual(result['candidates'][0]['similarity'], .80)

    def test_explicit_company_reference_restricts_candidates_without_faking_vector_score(self):
        service = Mock()
        service.search.return_value = [
            {'id': 'U_123', 'okved_code': '45.31', 'similarity': .95},
            {'id': 'U_1234', 'okved_code': '45.31', 'similarity': .90},
        ]
        event = news()[0].model_copy(update={'title': 'Уведомление для U_1234', 'text': 'Изменение договора U_1234.', 'topics': ['automotive']})
        with patch.object(self.reader, '_semantic', return_value=service):
            result = self.reader.match_news(event, as_of=AS_OF, limit=5)
        self.assertEqual([row['id'] for row in result['candidates']], ['U_1234'])
        self.assertEqual(result['candidates'][0]['similarity'], .90)
        self.assertNotIn('importance', result['candidates'][0])

    def test_reverse_search_excludes_classified_nonbusiness_without_model(self):
        with patch.object(self.reader, '_semantic') as semantic:
            result = self.reader.match_news(news()[0].model_copy(update={'topics': ['not_business']}), as_of=AS_OF)
        semantic.assert_not_called()
        self.assertEqual(result['candidates'], [])


if __name__ == '__main__': unittest.main()
