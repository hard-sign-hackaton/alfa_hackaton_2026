"""Evaluate bank retrieval and a small set of live company/news investigations."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from sqlalchemy import text
from bank_repository import BankReader
from company_repository import CompanyReader
from contracts import CompanyProfile, NewsEvent, Insight, validate_evidence
from database import DatabaseSettings, PostgresRepository
from database_agent import DatabaseResearchAgent
from langchain_provider import LangChainClient
from model_config import load_environment
from news_repository import NewsReader
from retrieval import timestamp
from tasks import NewsPreparation

CASES = [
    ('U_128194', '6fd817b6b18a3c411d8fd211415892665b9b818b72cc3d64c13f61fe937b10b7'),
    ('U_37452', '9bfb602e317f62a40ab4bd588e14178869a9ee317e02572c6083315e6f4fd66c'),
    ('U_46911', '1056dce3cfa282c8aee1ecd173c5273091e4715beda0b3930c733a3261c46b2e'),
]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def check(args, banks):
    with banks.documents.session() as session:
        counts = dict(session.execute(text('SELECT '
            '(SELECT count(*) FROM analytics_documents) AS documents, '
            '(SELECT count(*) FROM analytics_chunks) AS chunks, '
            '(SELECT count(*) FROM analytics_chunk_embeddings) AS vectors, '
            '(SELECT count(*) FROM analytics_tables) AS full_tables, '
            '(SELECT count(*) FROM news_articles) AS news, '
            '(SELECT count(*) FROM companies) AS companies')).one()._mapping)
        permissions = dict(session.execute(text("SELECT current_user AS role, "
            "has_table_privilege(current_user, 'analytics_chunks', 'SELECT') AS can_read, "
            "has_table_privilege(current_user, 'analytics_chunks', 'INSERT') AS can_insert, "
            "has_table_privilege(current_user, 'analytics_documents', 'UPDATE') AS can_update")).one()._mapping)
        chunks = list(session.scalars(text('SELECT embedding_text FROM analytics_chunks')))
    assert counts == dict(documents=9, chunks=138, vectors=138, full_tables=0, news=153, companies=12), counts
    assert permissions['can_read'] and not permissions['can_insert'] and not permissions['can_update']
    queries = []
    for query in ('ключевая ставка кредиты', 'потребительский спрос автомобили', 'сталь спрос'):
        sources = banks.search(query, as_of=args.as_of, limit=3)
        assert sources and all(not s.is_demo for s in sources)
        queries.append(dict(query=query, sources=[s.model_dump() for s in sources]))
    assert banks.search('ключевая ставка', as_of='2020-01-01T00:00:00+00:00') == []
    historical = banks.search('сталь', as_of='2022-01-01T00:00:00+00:00')
    assert historical and all(timestamp(s.published_at).year == 2021 for s in historical)
    provider = banks.embeddings.provider
    overhead = len(provider.document_window([], []))
    token_sizes = [len(provider.tokenize(value)) + overhead for value in chunks]
    assert max(token_sizes) <= provider.max_input_tokens, 'Bank chunks would be truncated'
    result = dict(as_of=args.as_of.isoformat(), counts=counts, permissions=permissions,
        profile=banks.embeddings.profile, max_input_tokens=max(token_sizes), token_limit=provider.max_input_tokens,
        queries=queries, metadata=banks.metadata, cutoff_checks_passed=True)
    save(args.output/'retrieval.json', result)
    print(json.dumps(dict(phase='check', counts=counts, max_input_tokens=max(token_sizes))), flush=True)


def analyze(args, banks):
    news, companies = NewsReader.from_env(), CompanyReader.from_env()
    repo = PostgresRepository(DatabaseSettings.from_env(), news_reader=news, company_reader=companies,
        bank_reader=banks, as_of=args.as_of)
    for index, (company_id, news_id) in enumerate(CASES, 1):
        client = LangChainClient()
        path = args.output/'analyses'/(company_id+'-'+news_id+'.json')
        previous = read(path) if path.exists() else {}
        if previous.get('signature') == client.model_signature() and 'result' in previous:
            client.close()
            continue
        row = dict(company_id=company_id, news_id=news_id, signature=client.model_signature())
        try:
            event = news.get_news(news_id, as_of=args.as_of)
            if args.prepared:
                prepared = NewsPreparation(classification=read(args.prepared/'classification'/(news_id+'.json'))['result'],
                    extraction=read(args.prepared/'extraction'/(news_id+'.json')))
                client._validate_news_evidence(prepared.classification, event)
                client._validate_news_evidence(prepared.extraction, event)
                client._preparations[hashlib.sha256(event.model_dump_json().encode()).hexdigest()] = prepared
                row['preparation_reused'] = True
            row['result'] = DatabaseResearchAgent(repo, client, as_of=args.as_of).run(company_id, news_id)
        except Exception as exc:
            row['error'] = type(exc).__name__ + ': ' + str(exc).replace(client.api_key, '[redacted]')[:200]
        finally:
            row['telemetry'] = previous.get('telemetry', []) + client.telemetry
            row['previous_errors'] = previous.get('previous_errors', []) + ([previous['error']] if 'error' in previous else [])
            client.close()
        save(path, row)
        print(json.dumps(dict(phase='analyze', done=index, total=len(CASES), ok='result' in row)), flush=True)


def report(args, banks):
    retrieval = read(args.output/'retrieval.json')
    analyses = [read(p) for p in sorted((args.output/'analyses').glob('*.json'))]
    metrics = [m for row in analyses for m in row.get('telemetry', [])]
    cases = []
    for row in analyses:
        if 'result' not in row:
            cases.append(dict(company_id=row['company_id'], error=row['error']))
            continue
        state = row['result']
        company = CompanyReader.from_env().get_company_profile(row['company_id'], as_of=args.as_of)
        event = NewsReader.from_env().get_news(row['news_id'], as_of=args.as_of)
        validate_evidence(Insight.model_validate(state['result']), company, event, state['retrieved_sources'])
        cited = {e['source_id'] for claim in state['result']['claims'] for e in claim['evidence'] if e['source_id'].startswith('bank:')}
        bank_sources = [s for s in state['retrieved_sources'] if s['kind'] == 'bank']
        cases.append(dict(company_id=row['company_id'], news_id=row['news_id'], title=event.title,
            status=state['result']['status'], bank_sources=len(bank_sources), cited_bank_sources=len(cited),
            brief=state.get('brief'),
            bank_tool_calls=[x for x in state['trace'] if x['tool']=='search_bank_analytics']))
    summary = dict(as_of=args.as_of.isoformat(), cases=cases, planned=len(CASES),
        completed=sum('result' in row for row in analyses),
        brief_completed=sum(row.get('result', {}).get('brief', {}).get('status')=='ready' for row in analyses),
        model_attempts=len(metrics), statuses=dict(Counter(m['status'] for m in metrics)),
        reported_cost_usd=sum((m.get('usage') or {}).get('cost', 0) or 0 for m in metrics),
        limitations=['Three selected cases are a functionality check, not an independent quality benchmark.',
            'OCR may contain errors. Full table grids and chart data are absent.',
            'Bank forecasts and historical reports are attributed context, not proof of company impact.',
            'Previous reports describe runs without bank context and remain unchanged.'])
    args.report_dir.mkdir(parents=True, exist_ok=True)
    cli_path = args.output/'default-cli'/'result.json'
    if cli_path.exists():
        cli = read(cli_path)
        validate_evidence(Insight.model_validate(cli['result']), CompanyProfile.model_validate(cli['company']),
            NewsEvent.model_validate(cli['event']), cli['retrieved_sources'])
        from brief import CompactResult
        compact_result = CompactResult.model_validate(cli['brief'])
        cli_metrics = read(args.output/'default-cli'/'telemetry.json')
        summary['default_cli'] = dict(company_id=cli['company_id'], news_id=cli['news_id'],
            status=cli['result']['status'], brief_status=compact_result.status,
            bank_sources=sum(s['kind']=='bank' for s in cli['retrieved_sources']),
            model_attempts=len(cli_metrics),
            reported_cost_usd=sum((m.get('usage') or {}).get('cost', 0) or 0 for m in cli_metrics))
        save(args.report_dir/'default-cli-result.json', cli)
        save(args.report_dir/'default-cli-brief.json', compact_result.model_dump())
    save(args.report_dir/'summary.json', summary)
    save(args.report_dir/'compact-results.json', [row['result']['brief'] for row in analyses if row.get('result', {}).get('brief')])
    save(args.report_dir/'results.json', dict(summary=summary, retrieval=retrieval, analyses=analyses))
    from bank_context_report import render
    (args.report_dir/'report.html').write_text(render(summary, retrieval, analyses), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True), flush=True)


def compact(args, banks):
    from brief import fallback_brief
    for path in sorted((args.output/'analyses').glob('*.json')):
        row = read(path)
        if 'result' not in row:
            continue
        client = LangChainClient()
        state = row['result']
        if row.get('brief_signature')==client.model_signature() and state.get('brief', {}).get('status')=='ready':
            client.close()
            continue
        company, event = CompanyProfile.model_validate(state['company']), NewsEvent.model_validate(state['event'])
        insight, prepared = Insight.model_validate(state['result']), NewsPreparation.model_validate(state['preparation'])
        result = fallback_brief(insight, company, event, prepared)
        try:
            result = client.brief(company, event, insight, prepared, state['retrieved_sources'])
            row.pop('brief_error', None)
        except Exception as exc:
            row['brief_error'] = type(exc).__name__ + ': '+str(exc).replace(client.api_key, '[redacted]')[:200]
        finally:
            row['telemetry'] += client.telemetry
            client.close()
        state['brief'] = result.model_dump()
        row['brief_signature'] = client.model_signature()
        save(path, row)
        print(json.dumps(dict(phase='compact', company_id=company.id, status=result.status)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['check', 'analyze', 'compact', 'report'])
    parser.add_argument('--output', type=Path, default=Path('/output/bank-context-20261022'))
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--report-dir', type=Path, default=Path('/app/research/evaluation/2026-10-22-bank'))
    args = parser.parse_args()
    load_environment()
    manifest_path = args.output/'manifest.json'
    if not manifest_path.exists():
        save(manifest_path, dict(as_of=datetime.now(timezone.utc).isoformat(), cases=CASES))
    args.as_of = timestamp(read(manifest_path)['as_of'])
    banks = BankReader.from_env()
    if banks is None or banks.mode != 'hybrid':
        parser.error('Read-only bank DB and BANK_SEARCH_MODE=hybrid required')
    globals()[args.phase](args, banks)


if __name__ == '__main__': main()
