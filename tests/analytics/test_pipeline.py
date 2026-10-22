"""Unit checks for analytics metadata, chunk normalization and layer boundaries."""
import ast
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.modules.analytics.dto import Manifest
from app.modules.analytics.identity import (
    document_id,
    parse_published_at,
    sha256_text,
    slugify,
)
from app.modules.analytics.services.importing import AnalyticsImportService

ROOT = Path(__file__).resolve().parents[2]


class FakeRepository:
    def __init__(self):
        self.saved = []
        self.runs = []

    def save_document(self, document, chunks, tables):
        self.saved.append((document, chunks, tables))
        return {'document': 'inserted', 'chunks': len(chunks), 'tables': len(tables)}

    def record_run(self, report):
        self.runs.append(report)


class MetadataTests(unittest.TestCase):
    def test_slug_and_date(self):
        self.assertEqual(slugify('Бонд_Бриф_14092026'), 'bond-brif-14092026')
        self.assertEqual(document_id('ALFA-7M26.pdf'), 'alfa-7m26')
        self.assertEqual(
            parse_published_at('7 сентября 2026\n\n## Заголовок'),
            datetime(2026, 9, 7, tzinfo=timezone.utc),
        )
        self.assertEqual(
            parse_published_at('опубликовано 11.09.2026'),
            datetime(2026, 9, 11, tzinfo=timezone.utc),
        )
        self.assertIsNone(parse_published_at('без даты'))
        self.assertEqual(len(sha256_text('x')), 64)

    def test_manifest_accepts_list_and_mapping(self):
        entry = {
            'source_name': 'ALFA-7M26.pdf',
            'title': 'Макростатистика 7М26',
            'published_at': '2026-09-07',
        }
        listed = Manifest.model_validate({'documents': [entry]})
        mapped = Manifest.model_validate({'documents': {'ALFA-7M26.pdf': entry}})
        self.assertEqual(listed.documents[0].published_at.year, 2026)
        self.assertEqual(mapped.documents[0].source_name, 'ALFA-7M26.pdf')


class ImportTests(unittest.TestCase):
    def fixture(self, directory: Path, *, manifest=None):
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
                'embedding_text': 'Документ: Макростатистика 7М26\nРаздел: Рынок труда\n\nТекст про рынок труда.',
                'pages': [1],
                'tables': [{'id': 'table-1', 'page': 2, 'part': 1, 'parts': 1}],
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
        if manifest is not None:
            (extracted / 'manifest.json').write_text(
                json.dumps(manifest, ensure_ascii=False), encoding='utf-8'
            )
        return extracted

    def test_import_infers_metadata_and_normalizes_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            extracted = self.fixture(Path(directory))
            repository = FakeRepository()
            report = AnalyticsImportService(repository).run(extracted)
            self.assertEqual(report['summary'], {'documents': 1, 'chunks': 2, 'tables': 1})
            document, chunks, tables = repository.saved[0]
            self.assertEqual(document.id, 'alfa-7m26')
            self.assertEqual(document.title, 'Макростатистика 7М26')
            self.assertEqual(document.published_at, datetime(2026, 9, 7, tzinfo=timezone.utc))
            self.assertEqual(document.doc_type, 'analytics')
            self.assertEqual([chunk.ordinal for chunk in chunks], [0, 1])
            self.assertEqual([chunk.pages for chunk in chunks], [[1], [2]])
            self.assertTrue(chunks[0].id.startswith('alfa-7m26#'))
            self.assertEqual(chunks[0].input_hash, sha256_text(chunks[0].embedding_text))
            self.assertEqual(chunks[1].chars, len('Текст про инфляцию.'))
            self.assertEqual(chunks[0].table_refs[0]['id'], 'alfa-7m26#table-1')
            self.assertEqual(tables[0].id, 'alfa-7m26#table-1')
            self.assertEqual(tables[0].nrows, 1)
            self.assertEqual(repository.runs[-1]['status'], 'ok')

    def test_manifest_overrides_metadata(self):
        manifest = {
            'schema_version': '1.0.0',
            'documents': [{
                'id': 'custom-doc',
                'source_name': 'ALFA-7M26.pdf',
                'title': 'Канонический заголовок',
                'subtitle': 'Подзаголовок',
                'doc_type': 'macro',
                'published_at': '2026-09-08T12:00:00+03:00',
                'tags': ['макро', 'труд'],
                'metadata': {'period': '7M2026'},
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            extracted = self.fixture(Path(directory), manifest=manifest)
            repository = FakeRepository()
            AnalyticsImportService(repository).run(extracted)
            document, chunks, _ = repository.saved[0]
            self.assertEqual(document.id, 'custom-doc')
            self.assertEqual(document.title, 'Канонический заголовок')
            self.assertEqual(document.subtitle, 'Подзаголовок')
            self.assertEqual(document.doc_type, 'macro')
            self.assertEqual(document.tags, ['макро', 'труд'])
            self.assertEqual(document.published_at.hour, 9)
            self.assertEqual(document.meta['period'], '7M2026')
            self.assertTrue(chunks[0].id.startswith('custom-doc#'))


class LayerTests(unittest.TestCase):
    def imports(self, path):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        return [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)] + [
            name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names
        ]

    def test_services_do_not_import_orm(self):
        for path in (ROOT / 'app/modules/analytics/services').glob('*.py'):
            imported = self.imports(path)
            self.assertFalse(any(
                name.startswith('sqlalchemy') or name in ('models', 'repositories')
                for name in imported
            ), str(path))

    def test_cli_does_not_import_sqlalchemy(self):
        imported = self.imports(ROOT / 'app/modules/analytics/cli.py')
        self.assertFalse(any(name.startswith('sqlalchemy') for name in imported))


if __name__ == '__main__':
    unittest.main()
