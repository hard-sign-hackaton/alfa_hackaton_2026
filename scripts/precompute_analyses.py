"""Precompute complete research for active company/news links; resume from PostgreSQL."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from threading import Lock, local
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'research' / 'ai'))


def pending_jobs(rows, *, refresh_bank_context=False):
    """Keep company identity even when companies belong to the same industry profile."""
    from bank_context import needs_bank_refresh
    return [row for row in rows if row['active'] and
            (not row['analysis_result'] or not row['analysis_result'].get('brief') or
             (refresh_bank_context and needs_bank_refresh(row['analysis_result'])))]


def main():
    from bank_repository import BankReader
    from company_repository import CompanyReader
    from contracts import CompanyProfile, Insight, NewsEvent, validate_evidence
    from database import DatabaseSettings, PostgresRepository
    from database_agent import DatabaseResearchAgent
    from model_config import load_environment
    from news_repository import NewsReader
    from provider import LangChainClient
    from retrieval import RetrievedSource
    from tasks import NewsPreparation
    from app.modules.links.repository import LinkRepository

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=3, choices=range(1, 5))
    parser.add_argument('--attempts', type=int, default=2, choices=range(1, 4))
    parser.add_argument('--limit', type=int)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--refresh-bank-context', action='store_true',
                        help='Rebuild old business analyses that have no bank excerpts or initial bank search')
    parser.add_argument('--output', type=Path, default=Path(os.environ.get('WEB_RUNTIME_DIR', ROOT / 'local_runtime' / 'web')) / 'precompute')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    load_environment()
    links = LinkRepository(os.environ['LINKS_DATABASE_URL'])
    rows = links.list(active_only=True)
    from bank_context import needs_bank_refresh
    jobs = pending_jobs(rows, refresh_bank_context=args.refresh_bank_context)
    def full_research(row):
        return not row['analysis_result'] or (args.refresh_bank_context and needs_bank_refresh(row['analysis_result']))
    if args.limit:
        jobs = jobs[:args.limit]
    print(json.dumps({'stage': 'plan', 'active_pairs': len(rows), 'jobs': len(jobs),
        'full_research': sum(full_research(r) for r in jobs),
        'brief_only': sum(not full_research(r) for r in jobs), 'workers': args.workers}), flush=True)
    if args.dry_run or not jobs:
        return
    args.output.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc)
    report = {'as_of': cutoff.isoformat(), 'active_pairs': len(rows), 'planned': len(jobs), 'completed': [], 'failed': []}
    report_lock, worker_local = Lock(), local()
    clients = []
    prepared = {}

    def save():
        temporary = args.output / 'report.tmp'
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(args.output / 'report.json')

    def repository():
        return PostgresRepository(DatabaseSettings.from_env(), news_reader=NewsReader.from_env(),
            company_reader=CompanyReader.from_env(), bank_reader=BankReader.from_env(), as_of=cutoff)

    # Preparation belongs to a publication and can be reused across different companies.
    preparation_client, preparation_repository = LangChainClient(), repository()
    if not preparation_client.api_key:
        raise ValueError('LLM_API_KEY is required')
    try:
        for row in rows:
            state = row['analysis_result']
            if not state:
                continue
            try:
                event = preparation_repository.get_news(row['news_id'], as_of=cutoff)
                value = NewsPreparation.model_validate(state['preparation'])
                preparation_client._validate_news_evidence(value.classification, event)
                if value.extraction:
                    preparation_client._validate_news_evidence(value.extraction, event)
                prepared[hashlib.sha256(event.model_dump_json().encode()).hexdigest()] = value
            except ValueError:
                continue
        preparation_client._preparations.update(prepared)
        for news_id in dict.fromkeys(row['news_id'] for row in jobs if full_research(row)):
            event = preparation_repository.get_news(news_id, as_of=cutoff)
            print(json.dumps({'stage': 'preparation', 'news_id': news_id}), flush=True)
            preparation_client.prepare(event)
        prepared.update(preparation_client._preparations)
        report['preparation_telemetry'] = preparation_client.telemetry
        save()
    finally:
        preparation_client.close()

    def run(row):
        if not hasattr(worker_local, 'client'):
            worker_local.client, worker_local.repository = LangChainClient(), repository()
            worker_local.client._preparations.update(prepared)
            with report_lock:
                clients.append(worker_local.client)
        client, repo = worker_local.client, worker_local.repository
        identity = {'company_id': row['company_id'], 'news_id': row['news_id']}
        use_existing = not full_research(row)
        for attempt in range(args.attempts):
            pair = links.ensure(row['company_id'], row['news_id'])
            run_id = uuid4().hex
            if not links.claim_analysis(pair, run_id):
                raise ValueError('Source changed before research')
            start = len(client.telemetry)
            print(json.dumps({'stage': 'brief' if use_existing else 'research', **identity, 'attempt': attempt + 1}), flush=True)
            try:
                if use_existing:
                    state = dict(row['analysis_result'])
                    company, event = CompanyProfile.model_validate(state['company']), NewsEvent.model_validate(state['event'])
                    insight, preparation = Insight.model_validate(state['result']), NewsPreparation.model_validate(state['preparation'])
                    sources = [RetrievedSource.model_validate(s) for s in state.get('retrieved_sources', [])]
                    validate_evidence(insight, company, event, sources)
                    state['brief'] = client.brief(company, event, insight, preparation, sources).model_dump()
                    state.pop('brief_error', None)
                else:
                    state = DatabaseResearchAgent(repo, client, as_of=cutoff).run(row['company_id'], row['news_id'])
                state['telemetry'] = state.get('telemetry', []) + client.telemetry[start:]
                if not links.analysis(pair, state, run_id=run_id):
                    raise ValueError('Source changed during research')
                result = {**identity, 'status': state['result']['status'], 'has_brief': bool(state.get('brief')),
                          'claims': len(state['result']['claims']), 'telemetry': client.telemetry[start:]}
                with report_lock:
                    report['completed'].append(result)
                    save()
                print(json.dumps({'stage': 'done', **identity, 'status': result['status']}), flush=True)
                return
            except Exception as error:
                links.analysis_failed(pair, run_id)
                # Old accepted claims may be insufficient for a grounded compact answer.
                # On retry rebuild the complete research instead of repeating the same brief.
                use_existing = False
                print(json.dumps({'stage': 'retry' if attempt + 1 < args.attempts else 'failed', **identity,
                                  'error_type': type(error).__name__}), flush=True)
                if attempt + 1 == args.attempts:
                    with report_lock:
                        report['failed'].append({**identity, 'error_type': type(error).__name__})
                        save()

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run, row) for row in jobs]
            for future in as_completed(futures):
                future.result()
    finally:
        for client in clients:
            client.close()
    remaining = pending_jobs(links.list(active_only=True), refresh_bank_context=args.refresh_bank_context)
    print(json.dumps({'stage': 'complete', 'completed': len(report['completed']), 'failed': len(report['failed']),
                      'remaining': len(remaining)}), flush=True)
    if report['failed'] or (not args.limit and remaining):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
