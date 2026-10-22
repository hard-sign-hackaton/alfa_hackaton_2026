"""Opt-in PostgreSQL checks for analytics storage and retrieval."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.modules.analytics.repositories import (
    AnalyticsEmbeddingRepository,
    AnalyticsRepository,
)
from app.modules.analytics.services.embedding import AnalyticsEmbeddingService
from app.modules.analytics.services.importing import AnalyticsImportService
from app.modules.analytics.services.search import AnalyticsSearchService
from app.shared.db.migrations import upgrade_database
from app.shared.db.session import get_engine, get_session_factory
from app.shared.embeddings.provider import EmbeddingModelInfo, normalize

URL = os.getenv('ANALYTICS_TEST_DATABASE_URL')


class FakeProvider:
    info = EmbeddingModelInfo('fake-e5', '0' * 40, 384, True)
    max_input_tokens = 512

    def tokenize(self, text):
        return [ord(char) % 100 for char in text]

    def document_window(self, title_tokens, body_tokens):
        return [0] + list(title_tokens) + [1] + list(body_tokens) + [2]

    def encode_windows(self, windows, batch_size=32):
        vector = normalize(np.ones(384, dtype=np.float32))
        return np.asarray([vector for _ in windows], dtype=np.float32)

    def encode_query(self, text):
        return normalize(np.ones(384, dtype=np.float32))


@unittest.skipUnless(URL, 'Set ANALYTICS_TEST_DATABASE_URL to a disposable *_test database')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not make_url(URL).database.endswith('_test'):
            raise ValueError('ANALYTICS_TEST_DATABASE_URL must point to a *_test database')
        upgrade_database(URL)
        cls.engine = get_engine(URL)
        cls.sessions = get_session_factory(URL)

    def setUp(self):
        with self.engine.begin() as connection:
            connection.execute(text('DELETE FROM analytics_chunk_embeddings'))
            connection.execute(text('DELETE FROM analytics_embedding_profiles'))
            connection.execute(text('DELETE FROM analytics_import_runs'))
            connection.execute(text('DELETE FROM analytics_documents'))

    def fixture(self, directory: Path):
        extracted = directory / 'extracted'
        extracted.mkdir()
        markdown = (
            '<!-- image -->\n\n7 сентября 2026\n\n'
            '## Макростатистика 7М26\n\n## Рынок труда\n\n'
            'Текст про рынок труда.\n\n<!-- page break -->\n\n'
            '## Инфляция\n\nТекст про инфляцию.'
        )
        (extracted / 'doc.json').write_text(json.dumps({
            'source_name': 'ALFA-7M26.pdf',
            'source_pdf': 'ALFA-7M26.pdf',
            'title': 'Макростатистика 7М26',
            'page_count': 3,
            'markdown': markdown,
            'tables': [{
                'id': 'table-1',
                'source': {'page': 2},
                'nrows': 1,
                'ncols': 2,
                'rows': [['a', 'b']],
                'warnings': [],
            }],
        }, ensure_ascii=False), encoding='utf-8')
        chunks = [
            {
                'doc_id': 'ALFA-7M26',
                'source_name': 'ALFA-7M26.pdf',
                'kind': 'text',
                'section_path': ['Рынок труда'],
                'text': 'Текст про рынок труда.',
                'pages': [1],
                'tables': [],
                'size': 10,
            },
            {
                'doc_id': 'ALFA-7M26',
                'source_name': 'ALFA-7M26.pdf',
                'kind': 'text',
                'section_path': ['Инфляция'],
                'text': 'Текст про инфляцию.',
                'pages': [2],
                'tables': [],
                'size': 8,
            },
        ]
        (extracted / 'chunks.jsonl').write_text(
            '\n'.join(json.dumps(item, ensure_ascii=False) for item in chunks),
            encoding='utf-8',
        )
        return extracted

    def test_import_embedding_idempotency_and_search(self):
        documents = AnalyticsRepository(self.sessions)
        vectors = AnalyticsEmbeddingRepository(self.sessions)
        with tempfile.TemporaryDirectory() as directory:
            extracted = self.fixture(Path(directory))
            report = AnalyticsImportService(documents).run(extracted)
            self.assertEqual(report['summary'], {'documents': 1, 'chunks': 2, 'tables': 1})
            self.assertEqual(documents.stats()['documents'], 1)
            self.assertEqual(documents.stats()['chunks'], 2)

            again = AnalyticsImportService(documents).run(extracted)
            self.assertEqual(again['documents'][0]['document'], 'unchanged')

            embedding_service = AnalyticsEmbeddingService(vectors, FakeProvider())
            result = embedding_service.run(batch_size=2)
            self.assertEqual(result['saved'], 2)
            self.assertEqual(documents.stats()['embeddings'], 2)

            # Re-import of unchanged content must preserve existing vectors.
            AnalyticsImportService(documents).run(extracted)
            self.assertEqual(documents.stats()['embeddings'], 2)

            text_hits = documents.search_text('инфляция')
            self.assertEqual(len(text_hits), 1)
            self.assertEqual(text_hits[0]['document_id'], 'alfa-7m26')

            vector_hits = AnalyticsSearchService(documents, embedding_service).search(
                'инфляция', top_k=5, mode='vector'
            )
            self.assertEqual(len(vector_hits), 2)
            self.assertTrue(all(hit['document_id'] == 'alfa-7m26' for hit in vector_hits))

            document = documents.get_document('alfa-7m26')
            self.assertEqual(document['chunk_count'], 2)
            self.assertEqual(document['table_count'], 1)
            chunks = documents.get_chunks('alfa-7m26')
            self.assertEqual([chunk['pages'] for chunk in chunks], [[1], [2]])
            self.assertEqual(documents.get_tables('alfa-7m26')[0]['nrows'], 1)


if __name__ == '__main__':
    unittest.main()
