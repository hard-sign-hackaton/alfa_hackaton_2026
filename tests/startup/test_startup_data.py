"""Snapshot validation and transactional restore into an isolated *_test database."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from load_startup_data import restore, validate_snapshot
from sql_snapshots import GROUPS, SEED_ROOT


class SnapshotTests(unittest.TestCase):
    def test_files_have_matching_checksums_and_fixed_table_sets(self):
        manifest, content = validate_snapshot(SEED_ROOT)
        self.assertEqual(set(content), set(GROUPS))
        self.assertEqual(manifest['groups']['news']['counts']['news_articles'], 153)
        self.assertNotIn('CREATE ROLE', ''.join(content.values()))
        self.assertNotIn('CREATE TABLE', ''.join(content.values()))

    def test_modified_sql_is_rejected_before_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)
            for path in SEED_ROOT.iterdir():
                if path.is_file():
                    (destination / path.name).write_bytes(path.read_bytes())
            with (destination / '04_links.sql').open('ab') as stream:
                stream.write(b'\nSELECT 1;\n')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                validate_snapshot(destination)


@unittest.skipUnless(os.environ.get('STARTUP_TEST_DATABASE_URL'), 'Set STARTUP_TEST_DATABASE_URL to an isolated *_test database')
class RestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from sqlalchemy.engine import make_url
        sys.path.insert(0, str(ROOT))
        from app.shared.db.migrations import upgrade_database
        target = make_url(os.environ['STARTUP_TEST_DATABASE_URL'])
        if not target.database.endswith('_test'):
            raise ValueError('Only a dedicated *_test database is allowed')
        upgrade_database(target.render_as_string(hide_password=False))
        cls.url = target.set(drivername='postgresql').render_as_string(hide_password=False)
        cls.manifest, cls.content = validate_snapshot(SEED_ROOT)
        cls.groups = ('news', 'companies', 'bank', 'links')
        cls.tables = [t for group in cls.groups for t in GROUPS[group][1]]

    def setUp(self):
        import psycopg
        from psycopg import sql
        self.connection = psycopg.connect(self.url, autocommit=True)
        self.connection.execute(sql.SQL('TRUNCATE {} RESTART IDENTITY CASCADE').format(
            sql.SQL(',').join(sql.Identifier('public', table) for table in self.tables)))

    def tearDown(self):
        self.connection.close()

    def load(self, manifest=None):
        return restore(self.connection, self.groups, manifest or self.manifest, self.content)

    def test_full_restore_has_bank_vectors_links_and_results_and_valid_sequences(self):
        result = self.load()
        self.assertEqual(result['status'], 'restored')
        self.assertEqual(result['counts']['analytics_chunk_embeddings'], 138)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM news_company_links WHERE analysis_result IS NOT NULL').fetchone()[0], 10)
        for table in ('news_embeddings', 'company_embeddings', 'analytics_chunk_embeddings'):
            value, maximum = self.connection.execute(
                "SELECT nextval(pg_get_serial_sequence(%s, 'id')), (SELECT max(id) FROM " + table + ')', (table,)).fetchone()
            self.assertGreater(value, maximum)

    def test_existing_user_changes_survive_second_restore(self):
        self.load()
        self.connection.execute("UPDATE news_articles SET title='Пользовательское изменение' WHERE id=(SELECT id FROM news_articles ORDER BY id LIMIT 1)")
        self.assertEqual(self.load()['status'], 'skipped_existing')
        self.assertEqual(self.connection.execute("SELECT count(*) FROM news_articles WHERE title='Пользовательское изменение'").fetchone()[0], 1)

    def test_partial_existing_database_is_not_filled_or_overwritten(self):
        self.connection.execute("INSERT INTO company_embedding_profiles(id,model,revision,dimensions,normalized,preparation) VALUES ('existing','local','revision',384,true,'existing')")
        self.assertEqual(self.load()['status'], 'skipped_existing')
        self.assertEqual(self.connection.execute('SELECT count(*) FROM news_articles').fetchone()[0], 0)

    def test_row_count_failure_rolls_back_all_groups(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['groups']['links']['counts']['news_company_links'] += 1
        with self.assertRaisesRegex(ValueError, 'row count'):
            self.load(manifest)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM news_articles').fetchone()[0], 0)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM companies').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
