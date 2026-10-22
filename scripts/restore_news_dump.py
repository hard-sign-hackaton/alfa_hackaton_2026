"""Restore a trusted PostgreSQL custom dump into an empty Compose database.

Requires Python 3.12 and Docker Compose; no Python packages or local pg tools.
Existing tables are never dropped or replaced.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '--profile', 'pipeline']


def run(*args, capture=False):
    return subprocess.run(COMPOSE + list(args), cwd=ROOT, check=True,
                          capture_output=capture, text=True).stdout


def sql(database, statement):
    return run('exec', '-T', 'postgres', 'psql', '-U', 'alfa_news', '-d', database,
               '-v', 'ON_ERROR_STOP=1', '-At', '-c', statement, capture=True).strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--file', type=Path, help='Local custom-format .dump file')
    source.add_argument('--url', help='Direct HTTPS download URL (not a preview page)')
    parser.add_argument('--sha256', help='Expected SHA-256 from the sender')
    parser.add_argument('--database', default='alfa_news_agent', help='New or empty target database')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', args.database):
        parser.error('Database must match [a-z][a-z0-9_]{0,62}')
    if args.sha256 and not re.fullmatch(r'[a-fA-F0-9]{64}', args.sha256):
        parser.error('Expected a 64-character SHA-256')
    if args.url and urlparse(args.url).scheme != 'https':
        parser.error('--url requires HTTPS')
    with tempfile.TemporaryDirectory(prefix='news-dump-') as temporary:
        dump = args.file.expanduser().resolve() if args.file else Path(temporary) / 'news.dump'
        if args.url:
            with urlopen(args.url, timeout=120) as response, dump.open('wb') as output:
                if urlparse(response.url).scheme != 'https':
                    raise ValueError('Download redirected outside HTTPS')
                shutil.copyfileobj(response, output)
        with dump.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            stream.seek(0)
            if stream.read(5) != b'PGDMP':
                raise ValueError('Expected a PostgreSQL custom dump, not HTML or plain SQL')
        if args.sha256 and checksum != args.sha256.lower():
            raise ValueError('SHA-256 mismatch; database was not touched')
        run('up', '-d', '--wait', 'postgres')
        exists = sql('postgres', f"SELECT 1 FROM pg_database WHERE datname='{args.database}'")
        if exists:
            tables = sql(args.database, "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                         "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
                         "AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S','f')")
            if int(tables):
                raise ValueError(f'Database {args.database} is not empty; choose a new --database')
        container_path = '/tmp/news-restore-' + uuid.uuid4().hex + '.dump'
        try:
            run('cp', str(dump), 'postgres:' + container_path)
            run('exec', '-T', 'postgres', 'pg_restore', '--list', container_path, capture=True)
            if not exists:
                run('exec', '-T', 'postgres', 'createdb', '-U', 'alfa_news', args.database)
            run('exec', '-T', 'postgres', 'pg_restore', '-U', 'alfa_news', '-d', args.database,
                '--no-owner', '--no-acl', '--single-transaction', '--exit-on-error', container_path)
        finally:
            run('exec', '-T', 'postgres', 'rm', '-f', container_path)
        counts = sql(args.database, "SELECT json_build_object('articles',(SELECT count(*) FROM news_articles),"
                     "'embeddings',(SELECT count(*) FROM news_embeddings),"
                     "'profiles',(SELECT count(*) FROM news_embedding_profiles),"
                     "'migration',(SELECT version_num FROM alembic_version))")
        print(json.dumps(dict(database=args.database, sha256=checksum, restored=json.loads(counts)), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
