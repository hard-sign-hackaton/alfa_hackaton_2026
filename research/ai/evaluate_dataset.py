"""Resumable live evaluation of company/news matching using existing model routes.

Raw runs stay in ignored live_results. No model-generated label is ground truth.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from typing import Literal

from pydantic import Field
from contracts import StrictModel, Evidence, evidence_sources
from dataset import CompanyDataset, DatasetRepository
from database_agent import DatabaseResearchAgent
from model_config import load_environment
from news_repository import NewsReader
from provider import LangChainClient
from ranking import rank_pair
from retrieval import timestamp

ROOT = Path(__file__).resolve().parents[2]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    temporary.replace(path)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class PairAssessment(StrictModel):
    company_id: str
    news_id: str
    relevance: Literal['direct', 'indirect', 'weak', 'unrelated']
    mechanism: str
    evidence: list[Evidence] = Field(min_length=1, max_length=6)
    limitations: list[str]


def load_corpus(reader, as_of):
    from app.modules.news.models import Article
    from sqlalchemy import select
    with reader.articles.session() as session:
        ids = session.scalars(select(Article.id).where(Article.published_at <= as_of).order_by(Article.published_at, Article.id)).all()
    return [reader.get_news(value, as_of=as_of) for value in ids]


def classify(args, dataset, reader, corpus, manifest):
    def job(event):
        path = args.output / 'classification' / (event.id + '.json')
        client = LangChainClient()
        signature = digest({'news': event.model_dump(), 'models': client.model_signature()})
        previous = read(path) if path.exists() else {}
        if previous.get('fingerprint') == signature and 'result' in previous:
            client.close()
            return {'cached': True, 'ok': 'result' in read(path)}
        result = {'fingerprint': signature, 'news_id': event.id, 'title': event.title}
        if previous and 'result' not in previous:
            # Preserve otherwise discarded responses for diagnosis of persistent schema/citation failures.
            from langchain_core.runnables import RunnableLambda
            original_model = client._model
            captures = []
            def capture(message):
                from tasks import TopicClassification
                entry = {'content': message.content, 'finish_reason': message.response_metadata.get('finish_reason')}
                try:
                    value = TopicClassification.model_validate_json(message.content)
                    client._validate_news_evidence(value, event)
                    entry['validation'] = 'ok'
                except Exception as exc:
                    entry['validation'] = type(exc).__name__ + ': ' + str(exc)[:800]
                captures.append(entry)
                save(args.output / 'diagnostics' / (event.id + '.json'), captures)
                return message
            client._model = lambda task, max_tokens=None, **kwargs: original_model(task, max_tokens, **kwargs) | RunnableLambda(capture)
        try:
            result['result'] = client.classify(event).model_dump()
        except Exception as exc:
            result['error'] = type(exc).__name__ + ': ' + str(exc).replace(client.api_key, '[redacted]')[:300]
        finally:
            result['previous_errors'] = previous.get('previous_errors', []) + ([previous['error']] if 'error' in previous else [])
            result['telemetry'] = previous.get('telemetry', []) + client.telemetry
            client.close()
        save(path, result)
        return {'ok': 'result' in result, 'news_id': event.id}
    counts = Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, future in enumerate(as_completed([pool.submit(job, event) for event in corpus]), 1):
            result = future.result()
            counts['ok' if result['ok'] else 'failed'] += 1
            print(json.dumps({'phase': 'classify', 'done': index, 'total': len(corpus), **result}), flush=True)
    save(args.output / 'classification-summary.json', dict(counts))


def retrieve(args, dataset, reader, corpus, manifest):
    from app.shared.embeddings.e5 import E5Provider
    from app.modules.news.services.embedding import NewsEmbeddingService
    profiles = reader.vectors.list_profiles()
    if len(profiles) != 1:
        raise ValueError('Evaluation requires one explicit compatible embedding profile')
    provider = E5Provider(revision=profiles[0]['revision'])
    if NewsEmbeddingService(reader.vectors, provider).profile != profiles[0]:
        raise ValueError('Embedding profile mismatch')
    rows = []
    for company_id in dataset.rows:
        for variant in ('profile', 'payments'):
            query = dataset.query(company_id, payments=variant == 'payments')
            hits = reader.vectors.search_pg(provider.encode_query(query), profiles[0]['id'], min(100, len(corpus)), as_of=args.as_of, query=query)
            rows.append({'company_id': company_id, 'variant': variant, 'query': query, 'hits': hits})
        print(json.dumps({'phase': 'retrieve', 'company_id': company_id}), flush=True)
    save(args.output / 'retrieval.json', {'profile': profiles[0], 'queries': rows})


def select_cases(args, dataset, reader, corpus, manifest):
    rankings = []
    for company_id in dataset.rows:
        company = dataset.profile(company_id)
        for event in corpus:
            path = args.output / 'classification' / (event.id + '.json')
            prepared = read(path) if path.exists() else {}
            if 'result' not in prepared:
                continue
            topics = prepared['result']['topics']
            result = rank_pair(company, event.model_copy(update={'topics': topics}), as_of=args.as_of)
            rankings.append({**result, 'title': event.title, 'topics': topics})
    save(args.output / 'baseline-ranking.json', rankings)
    retrieval = read(args.output / 'retrieval.json')['queries']
    representatives = []
    for group in dataset.groups.values():
        for code in dict.fromkeys(row['main']['okved']['code'].split('.')[0] for row in group['companies']):
            matching = [row for row in group['companies'] if row['main']['okved']['code'].split('.')[0] == code]
            representatives.append(max(matching, key=lambda row: row['main']['annual_revenue_rub'])['company_id'])
    selected_news = []
    for company_id in representatives:
        for variant in ('profile', 'payments'):
            row = next(row for row in retrieval if row['company_id'] == company_id and row['variant'] == variant)
            for hit in row['hits'][:2]:
                if hit['id'] not in selected_news:
                    selected_news.append(hit['id'])
    controls = ('льготного автокредитования', 'поддержки пароходств', 'ключевую ставку',
                'Ставки на перевозку российской нефти', 'Цены на овощи', 'футбольную',
                'ударе по логистическому центру в Ровно')
    for text in controls:
        event = next((event for event in corpus if text.lower() in event.title.lower()), None)
        if event is not None and event.id not in selected_news:
            selected_news.append(event.id)
    # Include the same news for all three sectors; comparisons are paired.
    ids = {event.id for event in corpus}
    cases = [{'company_id': company_id, 'news_id': news_id} for news_id in selected_news if news_id in ids for company_id in representatives]
    save(args.output / 'cases.json', {'representatives': representatives, 'selected_news': selected_news, 'pairs': cases,
        'selection': 'Union of top-2 profile/payment E5 candidates plus named domain/negative controls, crossed with one company per distinct OKVED class in each group. Biased diagnostic sample, not random or a holdout.'})
    print(json.dumps({'phase': 'select', 'ranked_pairs': len(rankings), 'selected_pairs': len(cases)}), flush=True)


def review(args, dataset, reader, corpus, manifest):
    events = {event.id: event for event in corpus}
    cases = read(args.output / 'cases.json')['pairs']
    def job(case):
        company_id, news_id = case['company_id'], case['news_id']
        company, event = dataset.profile(company_id), events[news_id]
        path = args.output / 'reviews' / (company_id + '-' + news_id + '.json')
        metrics = dataset.metrics(company_id, as_of=args.as_of)
        client = LangChainClient()
        fingerprint = digest({'company': company.model_dump(), 'news': event.model_dump(), 'metrics': [m.model_dump() for m in metrics], 'models': client.model_signature(), 'protocol': 1})
        previous = read(path) if path.exists() else {}
        if previous.get('fingerprint') == fingerprint and 'result' in previous:
            client.close()
            return {'cached': True, **case}
        sources = evidence_sources(company, event, metrics)
        payload = {'company_id': company_id, 'news_id': news_id, 'sources': sources,
            'question': None, 'instructions': 'Для диагностического исследования оцени связь новости с компанией. direct: явно затронут её вид деятельности; indirect: есть конкретный экономический канал через контрагентов, затраты, финансирование или спрос; weak: только общее тематическое сходство; unrelated: нет обоснованного канала. Не считай совпадение терминов доказательством. Для direct/indirect нужны точные цитаты из новости и из профиля либо платежных агрегатов. Не путай отрасль компании с отраслью её контрагентов. Агрегаты без периода не устанавливают текущую экспозицию. Оцени relevance и mechanism по переданной схеме, а не стандартный Insight. Это модельная оценка, не экспертная разметка.'}
        def validate(result):
            if result.company_id != company_id or result.news_id != news_id:
                raise ValueError('Identity mismatch')
            for item in result.evidence:
                if item.source_id not in sources or item.quote not in sources[item.source_id]:
                    raise ValueError('Invalid reference')
            if result.relevance in ('direct', 'indirect'):
                if not any(e.source_id == 'news:' + news_id for e in result.evidence) or not any(e.source_id.startswith(('company:', 'metric:')) for e in result.evidence):
                    raise ValueError('Missing paired evidence')
        result = {'fingerprint': fingerprint, **case}
        try:
            result['result'] = client._invoke('analysis', payload, PairAssessment, validate).model_dump()
        except Exception as exc:
            result['error'] = type(exc).__name__ + ': ' + str(exc).replace(client.api_key, '[redacted]')[:300]
        finally:
            result['previous_errors'] = previous.get('previous_errors', []) + ([previous['error']] if 'error' in previous else [])
            result['telemetry'] = previous.get('telemetry', []) + client.telemetry
            client.close()
        save(path, result)
        return {**case, 'ok': 'result' in result}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, future in enumerate(as_completed([pool.submit(job, case) for case in cases]), 1):
            print(json.dumps({'phase': 'review', 'done': index, 'total': len(cases), **future.result()}), flush=True)


def analyze(args, dataset, reader, corpus, manifest):
    cases = read(args.output / 'cases.json')['pairs']
    reviews = [read(path) for path in sorted((args.output / 'reviews').glob('*.json'))]
    # Up to two positive and one negative/control per group; keep a fixed upper bound.
    selected = []
    for company_id in read(args.output / 'cases.json')['representatives']:
        candidates = [r for r in reviews if r['company_id'] == company_id and 'result' in r]
        positive = [r for r in candidates if r['result']['relevance'] in ('direct', 'indirect')][:2]
        negative = [r for r in candidates if r['result']['relevance'] in ('weak', 'unrelated')][:1]
        selected.extend(positive + negative)
    if not selected:
        raise ValueError('No reviewed cases available')
    selection_path = args.output / 'analysis-cases.json'
    if selection_path.exists() and not args.refresh_analysis_selection:
        selected = read(selection_path)
    else:
        save(selection_path, [{key: row[key] for key in ('company_id', 'news_id')} for row in selected])
    # Run one client sequentially: prepare() cache reuses classification/extraction across companies.
    client = LangChainClient()
    from tasks import NewsPreparation, TopicClassification
    events = {event.id: event for event in corpus}
    try:
        for index, case in enumerate(selected, 1):
            company_id, news_id = case['company_id'], case['news_id']
            path = args.output / 'analyses' / (company_id + '-' + news_id + '.json')
            previous = read(path) if path.exists() else {}
            if 'result' in previous:
                print(json.dumps({'phase': 'analyze', 'done': index, 'total': len(selected), 'cached': True}), flush=True)
                continue
            before = len(client.telemetry)
            event = events[news_id]
            classification = TopicClassification.model_validate(read(args.output / 'classification' / (news_id + '.json'))['result'])
            result = {'company_id': company_id, 'news_id': news_id}
            try:
                extraction_path = args.output / 'extraction' / (news_id + '.json')
                if extraction_path.exists():
                    from tasks import EventExtraction
                    extraction = EventExtraction.model_validate(read(extraction_path)['result'])
                else:
                    extraction = client.extract(event) if classification.business_relevant else None
                    save(extraction_path, {'result': extraction.model_dump() if extraction else None})
                preparation = NewsPreparation(classification=classification, extraction=extraction)
                client._preparations[hashlib.sha256(event.model_dump_json().encode()).hexdigest()] = preparation
                # A fresh reader avoids cross-run mutable metadata while retaining cached E5 service.
                repository = DatasetRepository(dataset, reader)
                result['result'] = DatabaseResearchAgent(repository, client, as_of=args.as_of).run(company_id, news_id)
            except Exception as exc:
                result['error'] = type(exc).__name__ + ': ' + str(exc).replace(client.api_key, '[redacted]')[:300]
            result['previous_errors'] = previous.get('previous_errors', []) + ([previous['error']] if 'error' in previous else [])
            result['telemetry'] = previous.get('telemetry', []) + client.telemetry[before:]
            save(path, result)
            print(json.dumps({'phase': 'analyze', 'done': index, 'total': len(selected), 'ok': 'result' in result, 'company_id': company_id}), flush=True)
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['classify', 'retrieve', 'select', 'review', 'analyze'])
    parser.add_argument('--output', type=Path, default=ROOT / 'research/ai/live_results/dataset-20261022')
    parser.add_argument('--dataset', type=Path, default=ROOT / 'docs/companies/companies_analytics.json')
    parser.add_argument('--workers', type=int, default=4, choices=range(1, 5))
    parser.add_argument('--refresh-analysis-selection', action='store_true', help='Rebuild the bounded sample after pending pair reviews finish')
    args = parser.parse_args()
    load_environment()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / 'manifest.json'
    if manifest_path.exists():
        manifest = read(manifest_path)
        args.as_of = timestamp(manifest['as_of'])
        if manifest['dataset_sha256'] != hashlib.sha256(args.dataset.read_bytes()).hexdigest():
            raise ValueError('Dataset changed; select a new output directory')
    else:
        args.as_of = datetime.now(timezone.utc)
        manifest = {'as_of': args.as_of.isoformat(), 'dataset_sha256': hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                    'protocol': 1, 'notes': ['Model judgments are not ground truth.', 'Corpus is one short news snapshot. Payment periods unknown.']}
        save(manifest_path, manifest)
    dataset, reader = CompanyDataset(args.dataset), NewsReader.from_env()
    if reader is None:
        raise ValueError('NEWS_DATABASE_URL required')
    corpus = load_corpus(reader, args.as_of)
    save(args.output / 'corpus.json', [event.model_dump() for event in corpus])
    print(json.dumps({'phase': args.phase, 'news': len(corpus), 'companies': len(dataset.rows), 'as_of': args.as_of.isoformat()}), flush=True)
    globals()[args.phase if args.phase != 'select' else 'select_cases'](args, dataset, reader, corpus, manifest)


if __name__ == '__main__':
    main()
