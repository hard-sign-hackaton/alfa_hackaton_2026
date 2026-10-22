"""Upgrade news storage and grant a separate read-only role."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psycopg import sql
from app.shared.db.migrations import upgrade_database
from app.shared.db.session import get_engine
from app.modules.news.bootstrap import repositories
from app.modules.news.parsers.registry import SOURCES


def main():
    password = os.environ.get('NEWS_READER_PASSWORD')
    if not password:
        raise ValueError('NEWS_READER_PASSWORD is required')
    upgrade_database()
    repository, _ = repositories()
    repository.seed([value.source for value in SOURCES.values()])
    with get_engine().begin() as connection:
        raw = connection.connection.driver_connection
        exists = raw.execute("SELECT 1 FROM pg_roles WHERE rolname = 'analysis_news_reader'").fetchone()
        command = 'ALTER ROLE' if exists else 'CREATE ROLE'
        raw.execute(sql.SQL(command + ' analysis_news_reader LOGIN PASSWORD {}').format(sql.Literal(password)))
        raw.execute('ALTER ROLE analysis_news_reader SET default_transaction_read_only = on')
        raw.execute("ALTER ROLE analysis_news_reader SET statement_timeout = '5s'")
        raw.execute('GRANT USAGE ON SCHEMA public TO analysis_news_reader')
        raw.execute('GRANT SELECT ON news_articles,news_sources,news_embeddings,news_embedding_profiles TO analysis_news_reader')
        raw.execute('GRANT SELECT ON company_groups,companies,company_import_runs,company_embedding_profiles,company_embeddings TO analysis_news_reader')
    print('News storage ready; read-only role configured')


if __name__ == '__main__':
    main()
