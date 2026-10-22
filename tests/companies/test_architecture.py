"""Protect module boundaries and migration wiring for the company domain."""
import ast
import contextlib
import io
from pathlib import Path
import unittest

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]


def imports(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)] + [
        name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]


class ArchitectureTests(unittest.TestCase):
    def test_shared_has_no_dependency_on_modules(self):
        for path in (ROOT / 'app/shared').rglob('*.py'):
            self.assertFalse(any('app.modules' in name for name in imports(path)), str(path))

    def test_company_code_has_no_news_dependency(self):
        for path in (ROOT / 'app/modules/companies').rglob('*.py'):
            self.assertFalse(any('app.modules.news' in name for name in imports(path)), str(path))

    def test_services_do_not_import_orm(self):
        for path in (ROOT / 'app/modules/companies/services').glob('*.py'):
            imported = imports(path)
            self.assertFalse(any(name.startswith('sqlalchemy') or name in ('models', 'repositories')
                                 for name in imported), str(path))

    def test_cli_does_not_query_sqlalchemy(self):
        imported = imports(ROOT / 'app/modules/companies/cli.py')
        self.assertFalse(any(name.startswith('sqlalchemy') or name == 'models' for name in imported))

    def test_models_register_on_shared_metadata(self):
        from app.modules.companies.models import Company, CompanyEmbedding, CompanyGroup, CompanyImportRun
        from app.shared.db.base import Base
        for table in ('company_groups', 'companies', 'company_import_runs',
                      'company_embedding_profiles', 'company_embeddings'):
            self.assertIn(table, Base.metadata.tables)
        self.assertIs(CompanyGroup.__table__, Base.metadata.tables['company_groups'])
        self.assertIs(Company.__table__, Base.metadata.tables['companies'])
        self.assertIs(CompanyImportRun.__table__, Base.metadata.tables['company_import_runs'])
        self.assertIs(CompanyEmbedding.__table__, Base.metadata.tables['company_embeddings'])

    def test_migration_head_contains_companies(self):
        config = Config()
        config.set_main_option('script_location', str(ROOT / 'migrations'))
        script = ScriptDirectory.from_config(config)
        self.assertEqual(len(script.get_heads()), 1)
        self.assertIn('0004_companies', [revision.revision for revision in script.walk_revisions()])
        self.assertEqual(script.get_revision('0004_companies').down_revision, '0003_pgvector_only')

    def test_project_cli_dispatches_companies(self):
        from app.__main__ import main
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['companies', '--help'])
        self.assertEqual(error.exception.code, 0)

    def test_company_cli_help(self):
        from app.modules.companies.cli import main
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['--help'])
        self.assertEqual(error.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
