"""Protect module boundaries during parallel implementation of other domains."""
import ast
from pathlib import Path
import unittest
import shutil
import tempfile
import contextlib
import io
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect as inspect_orm
from app.shared.db.session import get_engine, get_session_factory
from app.modules.news.dto import ParsedArticle, NewsArticleDTO
from app.modules.news.normalization import normalize_article
from app.modules.news.parsers.registry import SOURCES

ROOT = Path(__file__).resolve().parents[2]


def imports(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)] + [
        name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]


class ArchitectureTests(unittest.TestCase):
    def test_removed_file_backend_is_not_available(self):
        from app.modules.news.cli import main
        for args in [['index', 'rebuild'], ['search', 'query', '--backend', 'faiss']]:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code, 2)
        for path in (ROOT / 'app').rglob('*.py'):
            self.assertFalse(any(name.startswith('faiss') for name in imports(path)), str(path))

    def test_shared_has_no_dependency_on_news(self):
        for path in (ROOT / 'app/shared').rglob('*.py'):
            self.assertFalse(any('app.modules' in name for name in imports(path)), str(path))

    def test_parsers_and_services_do_not_import_orm(self):
        for folder in ['parsers', 'services']:
            for path in (ROOT / 'app/modules/news' / folder).glob('*.py'):
                imported = imports(path)
                self.assertFalse(any(name.startswith('sqlalchemy') or name in ('models', 'repositories') for name in imported), str(path))

    def test_cli_and_search_do_not_query_sqlalchemy(self):
        for name in ['cli.py', 'services/search.py']:
            imported = imports(ROOT / 'app/modules/news' / name)
            self.assertFalse(any(n.startswith('sqlalchemy') or n == 'models' for n in imported))

    def test_shared_engine_and_factory_are_reused(self):
        url = 'postgresql+psycopg://unused:unused@localhost/never_connected'
        self.assertIs(get_engine(url), get_engine(url))
        self.assertIs(get_session_factory(url), get_session_factory(url))
        first, second = get_session_factory(url)(), get_session_factory(url)()
        self.assertIsNot(first, second)
        first.close()
        second.close()

    def test_parser_returns_incomplete_result_before_validation(self):
        source = SOURCES['kommersant']
        result = source.parse('https://www.kommersant.ru/doc/123', '<h1>Title without body or date</h1>')
        self.assertIsInstance(result, ParsedArticle)
        self.assertIsNone(result.published_at)
        self.assertIsNone(inspect_orm(result, raiseerr=False))
        with self.assertRaisesRegex(ValueError, 'body'):
            normalize_article(result)

    def test_project_migration_template_can_generate_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / 'versions').mkdir()
            shutil.copyfile(ROOT / 'migrations/script.py.mako', target / 'script.py.mako')
            config = Config()
            config.set_main_option('script_location', str(target))
            revision = ScriptDirectory.from_config(config).generate_revision('test_template', 'Template smoke', head='base')
            compile(Path(revision.path).read_text(encoding='utf-8'), revision.path, 'exec')


if __name__ == '__main__':
    unittest.main()
