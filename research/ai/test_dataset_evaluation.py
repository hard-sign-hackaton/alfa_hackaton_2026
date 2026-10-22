"""Regression checks for real-data adaptation and temporal/company boundaries."""
from datetime import timedelta
from pathlib import Path
import unittest

from dataset import CompanyDataset, DatasetRepository, LIMITATION
from retrieval import source_registry
from contracts import NewsEvent

PATH = Path(__file__).resolve().parents[2] / 'docs/companies/companies_analytics.json'


class DatasetEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = CompanyDataset(PATH)
        self.company_id = next(iter(self.dataset.rows))

    def test_real_profiles_preserve_all_twelve_identities(self):
        self.assertEqual(len(self.dataset.rows), 12)
        for company_id in self.dataset.rows:
            profile = self.dataset.profile(company_id)
            self.assertEqual(profile.id, company_id)
            self.assertEqual(profile.provenance, 'dataset')

    def test_missing_foreign_trade_is_unknown_not_no_exposure(self):
        self.assertIsNone(self.dataset.profile(self.company_id).trade_countries)

    def test_false_services_do_not_become_present(self):
        self.assertNotIn('Лизинг', self.dataset.profile(self.company_id).banking_services)
        self.assertIn('Кредиты', self.dataset.profile(self.company_id).banking_services)

    def test_snapshot_cannot_be_used_before_it_was_available(self):
        self.assertEqual(self.dataset.metrics(self.company_id, as_of=self.dataset.available_at - timedelta(seconds=1)), [])

    def test_metrics_preserve_numbers_and_limitations_without_period_invention(self):
        values = self.dataset.metrics(self.company_id, as_of=self.dataset.available_at)
        self.assertEqual(len(values), 5)
        for value in values:
            self.assertIn(LIMITATION, value.text)
            self.assertEqual(value.company_id, self.company_id)
        self.assertIn('5478280000', values[0].text)
        self.assertIn('35.66', values[1].text)

    def test_metrics_cannot_leak_into_another_company(self):
        values = self.dataset.metrics(self.company_id, as_of=self.dataset.available_at)
        other = self.dataset.profile(next(value for value in self.dataset.rows if value != self.company_id))
        event = NewsEvent(id='test', title='Test', text='Test', url='https://example.org/', published_at=self.dataset.available_at.isoformat(), topics=[])
        with self.assertRaises(ValueError):
            source_registry(values, other, event, as_of=self.dataset.available_at)

    def test_unloaded_bank_corpus_is_unavailable_not_an_empty_search(self):
        from database import DatabaseError
        with self.assertRaises(DatabaseError):
            DatasetRepository(self.dataset, None).search_bank_analytics('ставка', as_of=self.dataset.available_at)


if __name__ == '__main__':
    unittest.main()
