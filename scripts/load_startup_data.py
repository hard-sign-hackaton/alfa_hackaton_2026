"""Restore the bundled SQL snapshot once into empty, already migrated databases."""
import hashlib
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from sql_snapshots import GROUPS, SEED_ROOT


def validate_snapshot(root):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1 or set(manifest['groups']) != set(GROUPS):
        raise ValueError('Unknown startup snapshot version or groups')
    content = {}
    for group, (filename, tables) in GROUPS.items():
        item = manifest['groups'][group]
        raw = (root / filename).read_bytes()
        if item['file'] != filename or hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('SQL snapshot checksum mismatch: ' + filename)
        if set(item['counts']) != set(tables) or any(type(n) is not int or n < 0 for n in item['counts'].values()):
            raise ValueError('Invalid snapshot row counts')
        content[group] = raw.decode('utf-8')
    return manifest, content


def restore(connection, groups, manifest, content):
    """Atomic per database. Never mix a snapshot into existing source data."""
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(16420261023)')
        tables = [table for group in groups for table in GROUPS[group][1]]
        # Source registries are populated by news-db-init before the snapshot.
        guards = [table for table in tables if table != 'news_sources']
        for table in guards:
            if connection.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM public.{})').format(sql.Identifier(table))).fetchone()[0]:
                return {'status': 'skipped_existing', 'table': table}
        for group in groups:
            connection.execute(content[group], prepare=False)
        counts = {}
        for group in groups:
            for table, expected in manifest['groups'][group]['counts'].items():
                # The registry may contain additional sources from newer code.
                actual = connection.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table))).fetchone()[0]
                if (actual < expected if table == 'news_sources' else actual != expected):
                    raise ValueError('Restored row count mismatch: ' + table)
                counts[table] = actual
        return {'status': 'restored', 'counts': counts}


def main():
    enabled = os.environ.get('STARTUP_DATA_ENABLED', 'true').lower()
    if enabled in ('0', 'false', 'no'):
        print('Startup data disabled')
        return
    if enabled not in ('1', 'true', 'yes'):
        raise ValueError('STARTUP_DATA_ENABLED must be true or false')
    manifest, content = validate_snapshot(os.environ.get('STARTUP_DATA_DIR', SEED_ROOT))
    url = make_url(os.environ['DATABASE_URL']).set(drivername='postgresql').render_as_string(hide_password=False)
    with psycopg.connect(url, connect_timeout=10) as connection:
        result = restore(connection, ('news', 'companies', 'bank', 'links'), manifest, content)
        print(json.dumps({'database': 'sources', **result}))
        # Bank documents have no dependency on news/company rows. Older volumes may
        # already contain news but no analytics; fill only a completely empty bank group.
        if result['status'] == 'skipped_existing':
            bank = restore(connection, ('bank',), manifest, content)
            print(json.dumps({'database': 'bank', **bank}))
    with psycopg.connect(host=os.environ.get('DB_HOST', 'db'), port=int(os.environ.get('DB_PORT', '5432')),
                         dbname=os.environ.get('DB_NAME', 'alfa'), user='postgres',
                         password=os.environ['POSTGRES_PASSWORD'], connect_timeout=10) as connection:
        result = restore(connection, ('legacy',), manifest, content)
        print(json.dumps({'database': 'agent', **result}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Driver diagnostics may contain SQL/data or connection credentials.
        raise SystemExit('Startup data failed (' + type(error).__name__ + ')') from None
