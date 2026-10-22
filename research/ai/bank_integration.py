"""Read-only bank retrieval and citation tests on the disposable test database."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4

import numpy as np
from sqlalchemy import delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.modules.analytics.dto import EmbeddingInput
from app.modules.analytics.models import AnalyticsDocument, AnalyticsEmbeddingProfile
from app.modules.analytics.repositories import AnalyticsRepository, AnalyticsEmbeddingRepository
from app.modules.analytics.services.chunk_import import ChunkFileImportService
from app.shared.db.session import get_session_factory
from app.shared.embeddings.provider import normalize
from bank_repository import BankReader
from contracts import Insight, validate_evidence
from database_agent import DatabaseResearchAgent
from langchain_core.messages import AIMessage
from test_database_agent import ClientFixture, RepositoryFixture, calls

URL = os.environ.get('ANALYTICS_TEST_DATABASE_URL')


@unittest.skipUnless(URL, 'Separate analytics test database required')
class SharedBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not make_url(URL).database.endswith('_test'):
            raise ValueError('Disposable *_test database required')
        cls.token = 'bankbridge-' + uuid4().hex
        cls.profile_id = uuid4().hex
        cls.cutoff = datetime.now(timezone.utc)
        cls.documents = AnalyticsRepository(get_session_factory(URL))
        cls.vectors = AnalyticsEmbeddingRepository(get_session_factory(URL))
        cls.ids = [cls.token+'-old', cls.token+'-future']
        with tempfile.TemporaryDirectory() as directory:
            chunks, manifest = Path(directory)/'chunks.jsonl', Path(directory)/'manifest.json'
            manifest.write_text(json.dumps(dict(documents=[dict(id=key, source_name=key+'.pdf',
                title='Synthetic bank outlook', published_at=date.isoformat()) for key, date in
                zip(cls.ids, [cls.cutoff-timedelta(days=2), cls.cutoff+timedelta(days=2)])])), encoding='utf-8')
            chunks.write_text('\n'.join(json.dumps(dict(id=key+'#1', source_name=key+'.pdf',
                text='bankbridgeunique demand and inflation. Synthetic forecast.', pages=[3], section_path=['Demand']))
                for key in cls.ids), encoding='utf-8')
            importer = ChunkFileImportService(cls.documents)
            importer.run(chunks, manifest_path=manifest)
            profile = dict(id=cls.profile_id, model='synthetic-bank-vector', revision='fixture', dimensions=384,
                normalized=True, preparation='fixture')
            cls.vectors.ensure_profile(profile)
            for key in cls.ids:
                chunk = cls.documents.get_chunks(key)[0]
                cls.vectors.save_embedding(EmbeddingInput(chunk['id'], chunk['embedding_text'], chunk['input_hash']),
                    cls.profile_id, normalize(np.ones(384)).tolist())
            again = importer.run(chunks, manifest_path=manifest)
            assert all(item['document']=='unchanged' for item in again['documents'])
        embedding = SimpleNamespace(profile={'id': cls.profile_id}, repository=cls.vectors,
            encode_query=lambda query: normalize(np.ones(384)))
        cls.reader = BankReader(os.environ['NEWS_DATABASE_URL'], mode='hybrid', embeddings=embedding)

    @classmethod
    def tearDownClass(cls):
        with cls.documents.session.begin() as session:
            session.execute(delete(AnalyticsDocument).where(AnalyticsDocument.id.in_(cls.ids)))
            session.execute(delete(AnalyticsEmbeddingProfile).where(AnalyticsEmbeddingProfile.id==cls.profile_id))

    def test_reimport_preserves_vectors_and_cutoff_filters_before_limit(self):
        sources = self.reader.search('bankbridgeunique', as_of=self.cutoff, limit=1)
        self.assertEqual(len(sources), 1)
        self.assertIn(self.ids[0], sources[0].source_id)
        self.assertIn('pages=3', sources[0].locator)
        self.assertNotIn(self.ids[1], sources[0].source_id)

    def test_text_citations_are_stable_across_queries(self):
        reader = BankReader(os.environ['NEWS_DATABASE_URL'])
        first = reader.search('bankbridgeunique', as_of=self.cutoff)
        second = reader.search('demand', as_of=self.cutoff)
        self.assertEqual(first[0], next(s for s in second if s.source_id==first[0].source_id))

    def test_read_role_cannot_modify_bank_chunks(self):
        with self.assertRaises(SQLAlchemyError):
            with self.reader.documents.session.begin() as session:
                session.execute(text('UPDATE analytics_chunks SET text=text WHERE document_id=:id'), {'id':self.ids[0]})

    def test_real_bank_source_reaches_agent_and_validates_as_evidence(self):
        reader = self.reader
        class Repository(RepositoryFixture):
            def search_bank_analytics(inner, query, **kwargs):
                return reader.search(query, **kwargs)
        repo = Repository()
        client = ClientFixture([calls(('search_bank_analytics', {'query':'bankbridgeunique'})), AIMessage(content='Done')])
        # Fixtures use an older news date, while this test material is available now.
        state = DatabaseResearchAgent(repo, client, as_of=self.cutoff).run(repo.company.id, repo.news.id)
        self.assertTrue(any(s['kind']=='bank' and not s['is_demo'] for s in state['retrieved_sources']))
        validate_evidence(Insight.model_validate(state['result']), repo.company, repo.news, state['retrieved_sources'])


if __name__ == '__main__': unittest.main()
