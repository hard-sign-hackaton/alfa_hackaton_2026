"""Run integration suites against a separate test database."""
import os
from pathlib import Path
import subprocess
import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.shared.db.migrations import upgrade_database


def main():
    os.environ['PYTHONPATH'] = os.pathsep.join(filter(None, [str(ROOT), str(ROOT / 'research' / 'ai'), os.environ.get('PYTHONPATH')]))
    admin = make_url(os.environ['DATABASE_URL'])
    database = 'alfa_news_integration_test'
    with psycopg.connect(admin.set(drivername='postgresql').render_as_string(hide_password=False), autocommit=True) as connection:
        if not connection.execute('SELECT 1 FROM pg_database WHERE datname=%s', (database,)).fetchone():
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        startup_database = 'alfa_startup_snapshot_test'
        if not connection.execute('SELECT 1 FROM pg_database WHERE datname=%s', (startup_database,)).fetchone():
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(startup_database)))
    target = admin.set(database=database)
    url = target.render_as_string(hide_password=False)
    upgrade_database(url)
    with psycopg.connect(target.set(drivername='postgresql').render_as_string(hide_password=False)) as connection:
        connection.execute('GRANT USAGE ON SCHEMA public TO analysis_news_reader')
        connection.execute('GRANT SELECT ON news_sources,news_articles,news_embeddings,news_embedding_profiles TO analysis_news_reader')
        connection.execute('GRANT SELECT ON company_groups,companies,company_import_runs,company_embedding_profiles,company_embeddings TO analysis_news_reader')
        connection.execute('GRANT SELECT ON analytics_documents,analytics_chunks,analytics_tables,analytics_embedding_profiles,analytics_chunk_embeddings TO analysis_news_reader')
    os.environ['NEWS_TEST_DATABASE_URL'] = url
    os.environ['COMPANY_TEST_DATABASE_URL'] = url
    os.environ['ANALYTICS_TEST_DATABASE_URL'] = url
    os.environ['LINKS_TEST_DATABASE_URL'] = url
    os.environ['STARTUP_TEST_DATABASE_URL'] = admin.set(database=startup_database).render_as_string(hide_password=False)
    os.environ['NEWS_INTEGRATION_ADMIN_URL'] = url
    os.environ['NEWS_DATABASE_URL'] = target.set(username='analysis_news_reader', password=os.environ['NEWS_READER_PASSWORD']).render_as_string(hide_password=False)
    commands = [
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/news', '-v'],
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/companies', '-v'],
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/analytics', '-v'],
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/links', '-v'],
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'research/ai', '-p', 'test_*.py'],
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'research/contracts/t01', '-p', 'test_*.py'],
        [sys.executable, 'research/ai/database_integration.py', '-v'],
        [sys.executable, 'research/ai/news_integration.py', '-v'],
        [sys.executable, 'research/ai/bank_integration.py', '-v'],
        [sys.executable, 'research/contracts/t01/verify.py'],
        [sys.executable, 'research/contracts/validate.py'],
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/startup', '-v'],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
