"""Restore the bundled SQL snapshot once into empty, already migrated databases."""
import hashlib
import json
import os
import re
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


def restore_analyses(connection, content):
    """Fill cached results for identical sources; preserve newer work and edited data."""
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(16420261023)')
        # Stage the trusted, checksum-validated snapshot in temporary tables. No
        # source row or public sequence is changed by this upgrade path.
        for group in ('news', 'companies', 'links'):
            body = content[group]
            for table in GROUPS[group][1]:
                connection.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE public.{} INCLUDING ALL) ON COMMIT DROP').format(
                    sql.Identifier('seed_' + table), sql.Identifier(table)))
                body = body.replace('INSERT INTO public.' + table + ' ', 'INSERT INTO pg_temp.seed_' + table + ' ')
            body = re.sub(r'^SELECT pg_catalog\.setval\([^\n]+\);\s*$', '', body, flags=re.M)
            connection.execute(body, prepare=False)
        columns = [row[0] for row in connection.execute("SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='news_company_links' ORDER BY ordinal_position")]
        # Matching the complete company snapshot also catches payment edits that
        # do not change its embedding hash. Collection/import time is not content.
        updates = ('news_hash', 'company_hash', 'analysis_result', 'analysis_as_of', 'analysis_status',
                   'importance', 'importance_status', 'importance_reason', 'importance_evidence',
                   'importance_method', 'error_code')
        query = sql.SQL('''INSERT INTO public.news_company_links AS target ({columns})
            SELECT {selected} FROM pg_temp.seed_news_company_links s
            JOIN pg_temp.seed_companies sc ON sc.id=s.company_id
            JOIN public.companies c ON c.id=s.company_id
            JOIN pg_temp.seed_news_articles sn ON sn.id=s.news_id
            JOIN public.news_articles n ON n.id=s.news_id
            WHERE to_jsonb(c)-'imported_at'=to_jsonb(sc)-'imported_at'
              AND to_jsonb(n)-'collected_at'=to_jsonb(sn)-'collected_at'
              AND s.analysis_result IS NOT NULL AND s.analysis_result->'brief' IS NOT NULL
              AND s.analysis_as_of<=now() AND c.imported_at<=now() AND n.published_at<=now()
            ON CONFLICT (news_id,company_id) DO UPDATE SET {updates}, updated_at=now()
            WHERE target.analysis_status<>'running' AND (
                target.analysis_result IS NULL OR target.analysis_as_of<EXCLUDED.analysis_as_of OR
                (target.analysis_as_of=EXCLUDED.analysis_as_of AND
                 coalesce(target.analysis_result->'brief'->>'short_answer','')=''))''').format(
            columns=sql.SQL(',').join(map(sql.Identifier, columns)),
            selected=sql.SQL(',').join(sql.SQL('s.{}').format(sql.Identifier(c)) for c in columns),
            updates=sql.SQL(',').join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(c), sql.Identifier(c)) for c in updates))
        count = connection.execute(query).rowcount
        return {'status': 'updated_analyses', 'count': count}


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
            # Companies are reference data and do not depend on news. A pipeline
            # run may create news before web starts; in that case the combined
            # restore above is skipped and companies must still be filled.
            companies = restore(connection, ('companies',), manifest, content)
            print(json.dumps({'database': 'companies', **companies}))
            print(json.dumps({'database': 'analyses', **restore_analyses(connection, content)}))
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
