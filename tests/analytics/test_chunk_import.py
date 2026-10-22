import json
from pathlib import Path
import tempfile
import unittest

from app.modules.analytics.services.chunk_import import ChunkFileImportService


class Repository:
    def __init__(self):
        self.saved, self.runs, self.existing = [], [], {}

    def get_document(self, key):
        return self.existing.get(key)

    def save_document(self, document, chunks, tables):
        self.saved.append((document, chunks, tables))
        return dict(document='inserted', chunks=len(chunks), tables=len(tables))

    def record_run(self, report):
        self.runs.append(report)


class ChunkImportTests(unittest.TestCase):
    def fixture(self, root, *, unknown=False):
        rows = [dict(id='source#1', doc_id='source', source_name='source.pdf', text='First source fragment.',
                     section_path=['Demand'], pages=[2], tables=[dict(id='table-1', part=1, parts=2)])]
        if unknown:
            rows.append(dict(id='other#1', source_name='unknown.pdf', text='Unknown source.'))
        chunks, manifest = root/'chunks.jsonl', root/'manifest.json'
        chunks.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
        manifest.write_text(json.dumps(dict(documents=[dict(id='bank-source', source_name='source.pdf',
            title='Demand outlook', published_at='2026-09-01')])), encoding='utf-8')
        return chunks, manifest

    def test_import_preserves_provenance_without_fabricating_pdf_or_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            chunks, manifest = self.fixture(Path(directory))
            repo = Repository()
            report = ChunkFileImportService(repo).run(chunks, manifest_path=manifest)
        self.assertEqual(report['summary'], dict(documents=1, chunks=1, tables=0))
        document, fragments, tables = repo.saved[0]
        self.assertEqual(document.id, 'bank-source')
        self.assertEqual(document.extraction['mode'], 'chunks_only')
        self.assertIsNone(document.source_sha256)
        self.assertIsNone(document.page_count)
        self.assertEqual(fragments[0].pages, [2])
        self.assertEqual(fragments[0].table_refs[0]['id'], 'bank-source#table-1')
        self.assertFalse(tables)
        self.assertEqual(len(report['chunks_sha256']), 64)

    def test_unknown_source_rejects_whole_file_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            chunks, manifest = self.fixture(Path(directory), unknown=True)
            repo = Repository()
            with self.assertRaisesRegex(ValueError, 'Manifest'):
                ChunkFileImportService(repo).run(chunks, manifest_path=manifest)
            self.assertEqual(repo.saved, [])

    def test_duplicate_id_and_invalid_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            chunks, manifest = self.fixture(Path(directory))
            line = chunks.read_text(encoding='utf-8')
            for content in (line+'\n'+line, line+'\n{bad'):
                chunks.write_text(content, encoding='utf-8')
                with self.assertRaises(ValueError):
                    ChunkFileImportService(Repository()).run(chunks, manifest_path=manifest)

    def test_full_extraction_is_not_replaced_by_partial_material(self):
        with tempfile.TemporaryDirectory() as directory:
            chunks, manifest = self.fixture(Path(directory))
            repo = Repository()
            repo.existing['bank-source'] = dict(extraction={'extractor': 'original'})
            with self.assertRaisesRegex(ValueError, 'full extraction'):
                ChunkFileImportService(repo).run(chunks, manifest_path=manifest)
            self.assertEqual(repo.saved, [])


if __name__ == '__main__': unittest.main()
