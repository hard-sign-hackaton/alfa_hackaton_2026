"""Opt-in company persistence and vector tests on a disposable *_test database."""
from datetime import datetime, timezone
import hashlib
import os
import unittest
import uuid

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from app.modules.companies.dto import EmbeddingInput, NormalizedCompany
from app.modules.companies.identity import text_hash
from app.modules.companies.models import (Company, CompanyEmbedding, CompanyEmbeddingProfile,
                                          CompanyGroup as GroupRow, CompanyImportRun)
from app.modules.companies.normalization import normalize_dataset
from app.modules.companies.profiling import build_profile_text
from app.modules.companies.repositories import CompanyEmbeddingRepository, CompanyRepository
from app.modules.companies.services.embedding import CompanyEmbeddingService
from app.modules.companies.services.search import CompanySearchService
from app.shared.db.migrations import upgrade_database
from app.shared.db.session import get_session_factory
from app.shared.embeddings.provider import EmbeddingModelInfo, normalize

URL = os.getenv('COMPANY_TEST_DATABASE_URL')
DATASET = os.path.join(os.path.dirname(__file__), '..', '..', 'docs', 'companies', 'companies_analytics.json')


@unittest.skipUnless(URL, 'Set COMPANY_TEST_DATABASE_URL to a disposable *_test database')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not make_url(URL).database.endswith('_test'):
            raise ValueError('Integration tests require a dedicated *_test database')
        upgrade_database(URL)
        cls.sessions = get_session_factory(URL)
        cls.repo = CompanyRepository(cls.sessions)
        cls.vectors = CompanyEmbeddingRepository(cls.sessions)
        import json
        with open(DATASET, encoding='utf-8') as source:
            cls.dataset = normalize_dataset(json.load(source))
        cls.source_group = cls.dataset.groups[0]
        cls.source_company = cls.dataset.companies[0]

    def setUp(self):
        self.token = uuid.uuid4().hex
        self.group_id = 'test-group-' + self.token
        self.company_id = 'test-company-' + self.token
        self.profile_id = hashlib.sha256(('profile-' + self.token).encode()).hexdigest()
        self.group = self.source_group.model_copy(update={
            'group_id': self.group_id,
            'companies': [],
            'summary': self.source_group.summary.model_copy(update={
                'composition': self.source_group.summary.composition.model_copy(
                    update={'companies_count': 1}),
            }),
        })
        record = self.source_company.record.model_copy(update={
            'company_id': self.company_id,
            'main': self.source_company.record.main.model_copy(update={'group_id': self.group_id}),
        })
        self.company = NormalizedCompany(record=record, profile_text=build_profile_text(record),
                                         content_hash=text_hash(build_profile_text(record)))
        self.repo.save_group(self.group)
        self.repo.save_company(self.company)

    def tearDown(self):
        with self.sessions.begin() as session:
            session.execute(delete(CompanyEmbedding).where(CompanyEmbedding.profile_id == self.profile_id))
            session.execute(delete(Company).where(Company.id == self.company_id))
            session.execute(delete(GroupRow).where(GroupRow.id == self.group_id))
            session.execute(delete(CompanyEmbeddingProfile).where(CompanyEmbeddingProfile.id == self.profile_id))
            session.execute(delete(CompanyImportRun).where(CompanyImportRun.status.like('test-%')))

    def provider(self):
        class Provider(CompanyEmbeddingService):
            profile = dict(id=self.profile_id, model='test-only', revision='test-only', dimensions=384,
                           normalized=True, preparation='test-only')

            def encode_companies(inner, companies, batch_size=32):
                return [(normalize(np.arange(384, dtype=np.float32) + 1), 1, False) for _ in companies]

            def encode_query(inner, query):
                return normalize(np.arange(384, dtype=np.float32) + 1)
        return Provider(self.vectors, None)

    def test_upsert_invalidation_and_search(self):
        self.assertEqual(self.repo.save_company(self.company), 'unchanged')
        provider = self.provider()
        self.assertGreaterEqual(provider.run()['saved'], 1)
        self.assertEqual(provider.run()['saved'], 0)
        service = CompanySearchService(self.vectors, provider)
        result = {item['id']: item for item in service.search('fixture', 100)}
        self.assertIn(self.company_id, result)
        self.assertAlmostEqual(result[self.company_id]['similarity'], 1, places=5)

        changed_record = self.company.record.model_copy(update={
            'main': self.company.record.main.model_copy(update={'business_stage': 'Стремительный рост'}),
        })
        changed_text = build_profile_text(changed_record)
        changed = NormalizedCompany(record=changed_record, profile_text=changed_text,
                                    content_hash=text_hash(changed_text))
        self.assertEqual(self.repo.save_company(changed), 'updated')
        with self.sessions() as session:
            self.assertIsNone(session.scalar(select(CompanyEmbedding).where(
                CompanyEmbedding.company_id == self.company_id)))
        self.assertNotIn(self.company_id, [item['id'] for item in service.search('fixture', 100)])
        self.assertGreaterEqual(provider.run()['saved'], 1)
        self.assertIn(self.company_id, [item['id'] for item in service.search('fixture', 100)])

    def test_changed_company_cannot_save_old_embedding(self):
        provider = self.provider()
        self.vectors.ensure_profile(provider.profile)
        old = EmbeddingInput(self.company_id, self.company.profile_text, self.company.content_hash)
        changed_record = self.company.record.model_copy(update={
            'main': self.company.record.main.model_copy(update={'business_stage': 'Стремительный рост'}),
        })
        changed_text = build_profile_text(changed_record)
        changed = NormalizedCompany(record=changed_record, profile_text=changed_text,
                                    content_hash=text_hash(changed_text))
        self.repo.save_company(changed)
        self.assertFalse(self.vectors.save_embedding(old, self.profile_id,
                                                    normalize(np.ones(384)), 1, False))

    def test_get_list_and_profile_isolation(self):
        self.assertEqual(self.repo.get_company(self.company_id).company_id, self.company_id)
        self.assertTrue(any(item.company_id == self.company_id for item in self.repo.list_companies()))
        provider = self.provider()
        provider.run()
        foreign = dict(provider.profile, id=hashlib.sha256(('foreign-' + self.token).encode()).hexdigest())
        self.vectors.ensure_profile(foreign)
        try:
            self.assertEqual(self.vectors.search_pg(normalize(np.ones(384)), foreign['id'], 5), [])
        finally:
            with self.sessions.begin() as session:
                session.execute(delete(CompanyEmbeddingProfile).where(CompanyEmbeddingProfile.id == foreign['id']))

    def test_import_run_is_recorded(self):
        report = dict(started_at=datetime.now(timezone.utc).isoformat(),
                      finished_at=datetime.now(timezone.utc).isoformat(),
                      status='test-completed', report={})
        self.repo.record_run(report)
        with self.sessions() as session:
            self.assertIsNotNone(session.scalar(select(CompanyImportRun).where(
                CompanyImportRun.status == 'test-completed')))


if __name__ == '__main__':
    unittest.main()
