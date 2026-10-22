import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from jsonschema import Draft202012Validator

from app.modules.companies.identity import text_hash
from app.modules.companies.normalization import normalize_dataset
from app.modules.companies.profiling import build_profile_text
from app.modules.companies.services.embedding import CompanyEmbeddingService
from app.modules.companies.services.export import CompanyExportService
from app.modules.companies.services.ingestion import CompanyImportService
from app.modules.companies.services.search import CompanySearchService
from app.shared.embeddings.provider import EmbeddingModelInfo, normalize

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / 'docs/companies/companies_analytics.json'
AI_SCHEMA = ROOT / 'research/ai/results/company_profile.schema.json'


class FakeImportRepository:
    def __init__(self):
        self.groups, self.companies, self.runs = [], [], []

    def save_group(self, group):
        self.groups.append(group)
        return 'updated'

    def save_company(self, company):
        self.companies.append(company)
        return 'inserted'

    def record_run(self, report):
        self.runs.append(report)


class FakeExportRepository:
    def __init__(self, companies):
        self._companies = companies

    def list_companies(self):
        return list(self._companies)


class FakeEmbeddingRepository:
    def __init__(self, items):
        self.items = list(items)
        self.profile = None
        self.saved = []

    def ensure_profile(self, profile):
        self.profile = profile

    def pending(self, profile_id, limit):
        return [] if self.saved else self.items[:limit]

    def save_embedding(self, company, profile_id, vector, token_count, truncated):
        self.saved.append((company.company_id, profile_id, vector, token_count, truncated))
        return True


class FakeProvider:
    def __init__(self, max_input_tokens=512):
        self.info = EmbeddingModelInfo('test-only', 'test-revision', 384, True)
        self.max_input_tokens = max_input_tokens

    def tokenize(self, text):
        return [] if not text else [1] * max(1, len(text) // 8)

    def document_window(self, title_tokens, body_tokens):
        return ([0] + self.tokenize('passage: ') + list(title_tokens)
                + self.tokenize('\n\n') + list(body_tokens) + [0])

    def encode_windows(self, windows, batch_size=32):
        return normalize(np.tile(np.arange(1, 385, dtype=np.float32), (len(windows), 1)))

    def encode_query(self, text):
        return normalize(np.arange(1, 385, dtype=np.float32))


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = normalize_dataset(json.loads(DATASET.read_text(encoding='utf-8')))
        cls.company = cls.dataset.companies[0]

    def test_real_snapshot_shape(self):
        self.assertEqual(len(self.dataset.groups), 3)
        self.assertEqual(len(self.dataset.companies), 12)
        self.assertEqual(self.company.company_id, 'U_128194')
        self.assertEqual(self.company.record.main.group_id, 'group_132767_sb')
        self.assertTrue(all(company.content_hash for company in self.dataset.companies))

    def test_profile_contains_matching_signals(self):
        text = self.company.profile_text
        for expected in ('45.31.1', 'Воронежская область', 'Отрасли контрагентов',
                         'География контрагентов', 'Банковские услуги'):
            self.assertIn(expected, text)

    def test_profile_hash_changes_with_content(self):
        record = self.company.record
        changed = record.model_copy(update={
            'main': record.main.model_copy(update={'business_stage': 'Стремительный рост'}),
        })
        changed_text = build_profile_text(changed)
        self.assertNotEqual(changed_text, self.company.profile_text)
        self.assertNotEqual(text_hash(changed_text), self.company.content_hash)

    def test_import_report_and_dry_run(self):
        repository = FakeImportRepository()
        report = CompanyImportService(repository).import_file(DATASET)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['groups'], 3)
        self.assertEqual(report['companies'], 12)
        self.assertEqual(report['inserted'], 12)
        self.assertEqual(len(repository.groups), 3)
        self.assertEqual(len(repository.companies), 12)
        dry = CompanyImportService(None).import_file(DATASET, dry_run=True)
        self.assertEqual(dry['status'], 'validated')
        self.assertEqual(dry['validated'], 12)

    def test_invalid_dataset_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            path.write_text(json.dumps({'meta': {}, 'groups': []}), encoding='utf-8')
            report = CompanyImportService(None).import_file(path, dry_run=True)
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(report['errors'])

    def test_ai_export_matches_saved_contract(self):
        records = CompanyExportService(FakeExportRepository(
            [company.record for company in self.dataset.companies])).export(ai=True)
        schema = json.loads(AI_SCHEMA.read_text(encoding='utf-8'))
        validator = Draft202012Validator(schema)
        for record in records:
            validator.validate(record)
        self.assertEqual({record['provenance'] for record in records}, {'dataset'})
        self.assertTrue(all(record['source_ref'].startswith('docs/companies/companies_analytics.json#')
                            for record in records))
        first = next(record for record in records if record['id'] == 'U_128194')
        self.assertEqual(first['banking_services'], ['cash_register', 'credit', 'payroll'])
        self.assertIsNone(first['trade_countries'])

    def test_ingestion_export_returns_validated_payload(self):
        records = CompanyExportService(FakeExportRepository(
            [company.record for company in self.dataset.companies])).export()
        self.assertEqual(records[0]['company_id'], 'U_128194')
        self.assertIn('payments', records[0])


class EmbeddingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = normalize_dataset(json.loads(DATASET.read_text(encoding='utf-8')))
        cls.company = cls.dataset.companies[0]

    def test_window_respects_model_budget(self):
        service = CompanyEmbeddingService(None, FakeProvider(max_input_tokens=32))
        ids, token_count, truncated = service.window(self.company)
        self.assertLessEqual(len(ids), 32)
        self.assertEqual(token_count, len(ids))
        self.assertTrue(truncated)

    def test_embedding_run_saves_profile_vector(self):
        repository = FakeEmbeddingRepository([self.company])
        provider = FakeProvider()
        result = CompanyEmbeddingService(repository, provider).run()
        self.assertEqual(result['saved'], 1)
        self.assertEqual(result['concurrently_changed'], 0)
        self.assertEqual(len(repository.saved), 1)
        self.assertEqual(repository.saved[0][0], self.company.company_id)
        self.assertIsNotNone(repository.profile)

    def test_provider_failure_does_not_save_vectors(self):
        repository = FakeEmbeddingRepository([self.company])

        class Failing(CompanyEmbeddingService):
            def encode_companies(self, companies):
                raise RuntimeError('model unavailable')

        with self.assertRaises(RuntimeError):
            Failing(repository, FakeProvider()).run()
        self.assertEqual(repository.saved, [])

    def test_search_validates_input(self):
        class Repo:
            def search_pg(self, vector, profile_id, top_k):
                return [dict(company_id='U_1', similarity=1.0)]

        class Embeddings:
            profile = {'id': 'profile'}
            def encode_query(self, query):
                return normalize(np.arange(1, 385, dtype=np.float32))

        service = CompanySearchService(Repo(), Embeddings())
        with self.assertRaises(ValueError):
            service.search('   ')
        with self.assertRaises(ValueError):
            service.search('news', 0)
        self.assertEqual(service.search('news')[0]['company_id'], 'U_1')


if __name__ == '__main__':
    unittest.main()
