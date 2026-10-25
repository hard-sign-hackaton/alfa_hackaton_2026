"""Export Compose databases into plain SQL snapshots without roles or credentials."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

from sql_snapshots import GROUPS, SEED_ROOT

ROOT = Path(__file__).resolve().parents[1]
SECTION = re.compile(r'^--\n-- (?:Data for Name|Name): ([^;]+); Type: (TABLE DATA|SEQUENCE SET); Schema: public; Owner: [^\n]*\n--\n', re.M)


# pg_dump --column-inserts uses SQL literals, which may contain real newlines.
SQL_LITERAL = r"E'(?:\\.|''|[^'])*'|'(?:''|[^'])*'"
INSERT_ROW = re.compile(r'^INSERT INTO public\.(?:news_sources|news_articles|news_embeddings|news_company_links) '
                        r'\([^;]+?\) VALUES \((?:' + SQL_LITERAL + r'|[^\';])*\) ON CONFLICT DO NOTHING;', re.M)


def without_expert_records(dump):
    def keep(match):
        literals = re.findall(SQL_LITERAL, match.group())
        return '' if any(re.fullmatch(r"'(?:demo:[a-f0-9]{32}:[0-3]|expert-demo:[a-f0-9]{32})'", value)
                         for value in literals) else match.group()
    filtered = INSERT_ROW.sub(keep, dump)
    if re.search(r"'(?:demo:[a-f0-9]{32}:[0-3]|expert-demo:[a-f0-9]{32})'", filtered):
        raise ValueError('Could not safely exclude expert records from SQL export')
    return filtered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--news-database', required=True)
    parser.add_argument('--agent-database', default='alfa')
    parser.add_argument('--docker', default='docker')
    parser.add_argument('--output', type=Path, default=SEED_ROOT)
    args = parser.parse_args()
    for name in (args.news_database, args.agent_database):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', name):
            parser.error('Invalid database name')

    def run(service, *command):
        result = subprocess.run([args.docker, 'compose', 'exec', '-T', service, *command],
                                cwd=ROOT, capture_output=True)
        if result.returncode:
            raise RuntimeError('Database export command failed')
        return result.stdout.decode('utf-8')

    output = {}
    manifest = {'version': 1, 'exported_at': datetime.now(timezone.utc).isoformat(), 'groups': {}}
    for service, user, database, group_names in (
        ('postgres', 'alfa_news', args.news_database, ('news', 'companies', 'bank', 'links')),
        ('db', 'postgres', args.agent_database, ('legacy',)),
    ):
        tables = [table for group in group_names for table in GROUPS[group][1]]
        names = ','.join("'" + table + "'" for table in tables)
        sequences = json.loads(run(service, 'psql', '-U', user, '-d', database, '-At', '-c',
            "SELECT coalesce(json_object_agg(table_name, sequence), '{}'::json) FROM "
            "(SELECT table_name, pg_get_serial_sequence('public.' || table_name, column_name) AS sequence "
            f"FROM information_schema.columns WHERE table_schema='public' AND column_name='id' AND table_name IN ({names})) s "
            "WHERE sequence IS NOT NULL;"))
        table_flags = [flag for name in tables + list(sequences.values()) for flag in ('--table', name)]
        dump = run(service, 'pg_dump', '-U', user, '-d', database, '--data-only', '--no-owner',
                   '--no-acl', '--no-comments', '--column-inserts', '--on-conflict-do-nothing', *table_flags)
        if service == 'postgres':
            dump = without_expert_records(dump)
            manifest['analysis_coverage'] = json.loads(run(service, 'psql', '-U', user, '-d', database, '-At', '-c',
                "SELECT json_build_object('active_pairs', count(*) FILTER (WHERE active), "
                "'analyses', count(analysis_result), "
                "'active_with_analysis', count(*) FILTER (WHERE active AND analysis_result IS NOT NULL), "
                "'active_with_brief', count(*) FILTER (WHERE active AND analysis_result->'brief' IS NOT NULL "
                "AND analysis_result->'brief' <> 'null'::jsonb), "
                "'active_with_bank_context', count(*) FILTER (WHERE active AND EXISTS (SELECT 1 "
                "FROM jsonb_array_elements(analysis_result->'retrieved_sources') s WHERE s->>'kind'='bank')), "
                "'active_citing_bank', count(*) FILTER (WHERE active AND EXISTS (SELECT 1 "
                "FROM jsonb_array_elements(analysis_result->'result'->'claims') c "
                "CROSS JOIN jsonb_array_elements(c->'evidence') e WHERE e->>'source_id' LIKE 'bank:%')), "
                "'supported', count(*) FILTER (WHERE analysis_result->'result'->>'status'='supported'), "
                "'insufficient_data', count(*) FILTER (WHERE analysis_result->'result'->>'status'='insufficient_data')) "
                "FROM news_company_links WHERE news_id NOT LIKE 'demo:%';"))
        dump = re.sub(r'^\\(?:un)?restrict[^\n]*\n', '', dump, flags=re.M)
        sections = list(SECTION.finditer(dump))
        if not sections or '\\' in dump[:sections[0].start()]:
            raise ValueError('Unsupported pg_dump format')
        # Session settings only; schema and roles remain managed by migrations/init.sql.
        prefix = dump[:sections[0].start()]
        prefix = re.sub(r'^SET ', 'SET LOCAL ', prefix, flags=re.M)
        prefix = prefix.replace("set_config('search_path', '', false)", "set_config('search_path', '', true)")
        chunks = {}
        for index, match in enumerate(sections):
            end = sections[index + 1].start() if index + 1 < len(sections) else len(dump)
            chunks[match.group(1)] = dump[match.start():end]
        for group in group_names:
            filename, group_tables = GROUPS[group]
            selected = list(group_tables) + [sequences[t].split('.')[-1] for t in group_tables if t in sequences]
            missing = set(group_tables) - chunks.keys()
            if missing:
                raise ValueError('Tables missing from SQL snapshot: ' + ', '.join(sorted(missing)))
            content = ((prefix + '\n'.join(chunks[name] for name in selected if name in chunks)).rstrip() + '\n').encode('utf-8')
            if re.search(rb'sk-[A-Za-z0-9_-]{15,}|miro\.com/app/board', content):
                raise ValueError('Snapshot contains a credential or board reference')
            counts = {}
            for table in group_tables:
                # pg_dump column-inserts emits one INSERT per row. Match only table statement starts.
                counts[table] = len(re.findall(r'^INSERT INTO public\.' + re.escape(table) + r' \(', chunks[table], re.M))
            output[filename] = content
            manifest['groups'][group] = {'file': filename, 'sha256': hashlib.sha256(content).hexdigest(), 'counts': counts}
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, content in output.items():
        (args.output / filename).write_bytes(content)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({name: item['counts'] for name, item in manifest['groups'].items()}, indent=2))


if __name__ == '__main__':
    main()
