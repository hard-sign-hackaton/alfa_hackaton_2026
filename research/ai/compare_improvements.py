"""Paired comparison on a frozen corpus; model labels are not ground truth."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path

from contracts import NewsEvent, Insight, validate_evidence
from database_agent import DatabaseResearchAgent
from dataset import CompanyDataset, DatasetRepository
from evaluate_dataset import save, read, ROOT
from grounding import finalize_insight
from langchain_provider import LangChainClient
from model_config import load_environment
from news_repository import NewsReader
from ranking import rank_pair, industry_topics
from retrieval import timestamp
from tasks import TopicClassification, NewsPreparation, EventExtraction


def baseline_snapshot():
    return read(ROOT / 'research/evaluation/2026-10-22/evaluation.json')


def analysis_cases():
    return [{key: row[key] for key in ('company_id', 'news_id')} for row in baseline_snapshot()['analyses']]


def retrieval(args, dataset, reader, events):
    reader.mode = 'hybrid'
    classifications = {row['news_id']: row['result'] for path in (args.output / 'classification').glob('*.json') if 'result' in (row := read(path))}
    results, ranks = [], []
    for company_id in dataset.rows:
        company = dataset.profile(company_id)
        result = reader.match_company(company, as_of=args.as_of, metrics=dataset.metrics(company_id, as_of=args.as_of),
                                      classifications=classifications, limit=10)
        results.append(result)
        for event in events:
            if event.id in classifications:
                result = rank_pair(company, event.model_copy(update={'topics': classifications[event.id]['topics']}), as_of=args.as_of)
                ranks.append({**result, 'title': event.title})
        print(json.dumps({'company_id': company_id, 'candidates': len(results[-1]['candidates'])}), flush=True)
    save(args.output / 'company-matches.json', results)
    save(args.output / 'ranking-v2.json', ranks)


def analyze(args, dataset, reader, events):
    reader.mode = 'hybrid'
    cases = analysis_cases()
    by_id = {event.id: event for event in events}
    client = LangChainClient()
    try:
        for index, case in enumerate(cases, 1):
            company_id, news_id = case['company_id'], case['news_id']
            path = args.output / 'analyses' / (company_id + '-' + news_id + '.json')
            previous = read(path) if path.exists() else {}
            if previous.get('signature') == client.model_signature() and 'result' in previous:
                continue
            before = len(client.telemetry)
            row = {**case, 'signature': client.model_signature()}
            try:
                event = by_id[news_id]
                classification = TopicClassification.model_validate(read(args.output / 'classification' / (news_id + '.json'))['result'])
                extraction_path = args.output / 'extraction' / (news_id + '.json')
                if extraction_path.exists():
                    extraction = EventExtraction.model_validate(read(extraction_path))
                else:
                    extraction = client.extract(event) if classification.business_relevant else None
                    if extraction: save(extraction_path, extraction.model_dump())
                prepared = NewsPreparation(classification=classification, extraction=extraction)
                client._preparations[hashlib.sha256(event.model_dump_json().encode()).hexdigest()] = prepared
                row['result'] = DatabaseResearchAgent(DatasetRepository(dataset, reader), client, as_of=args.as_of).run(company_id, news_id)
            except Exception as exc:
                row['error'] = type(exc).__name__ + ': ' + str(exc).replace(client.api_key, '[redacted]')[:200]
            row['telemetry'] = previous.get('telemetry', []) + client.telemetry[before:]
            row['previous_errors'] = previous.get('previous_errors', []) + ([previous['error']] if 'error' in previous else [])
            save(path, row)
            print(json.dumps({'phase': 'analyze', 'done': index, 'total': len(cases), 'ok': 'result' in row}), flush=True)
    finally:
        client.close()


def report(args, dataset, reader, events):
    old = baseline_snapshot()
    labels = {(row['company_id'], row['news_id']): row['result']['relevance'] for row in old['reviews'] if 'result' in row}
    matches = read(args.output / 'company-matches.json')
    comparisons = []
    old_positive = {key for key, value in labels.items() if value in ('direct', 'indirect')}
    found_before, found_after = set(), set()
    for company_id in old['cases']['representatives']:
        before = next(row for row in old['retrieval'] if row['company_id'] == company_id and row['variant'] == 'profile')['hits'][:5]
        after = next(row for row in matches if row['company_id'] == company_id)['candidates'][:5]
        for variant, rows, found in [('before', before, found_before), ('after', after, found_after)]:
            judged = [labels[(company_id, row['id'])] for row in rows if (company_id, row['id']) in labels]
            found.update((company_id, row['id']) for row in rows if (company_id, row['id']) in old_positive)
            comparisons.append({'company_id': company_id, 'variant': variant, 'returned': len(rows), 'judged': len(judged),
                'model_positive': sum(value in ('direct', 'indirect') for value in judged), 'unjudged': len(rows) - len(judged)})
    files = list((args.output / 'classification').glob('*.json')) + list((args.output / 'analyses').glob('*.json'))
    saved = [read(path) for path in files]
    metrics = [metric for row in saved for metric in row.get('telemetry', [])]
    classifications = [read(path) for path in (args.output / 'classification').glob('*.json')]
    analyses = [read(path) for path in (args.output / 'analyses').glob('*.json')]
    for row in analyses:
        if 'result' in row:
            state = row['result']
            validate_evidence(Insight.model_validate(state['result']), dataset.profile(row['company_id']),
                              next(event for event in events if event.id == row['news_id']), state['retrieved_sources'])
    correction = []
    for row in old['analyses']:
        if 'result' not in row: continue
        previous = row['result']['result']
        fixed = finalize_insight(Insight.model_validate(previous), dataset.profile(row['company_id']),
                                 next(event for event in events if event.id == row['news_id']))
        correction.append({'company_id': row['company_id'], 'news_id': row['news_id'], 'before': previous['summary'], 'after': fixed.summary})
    summary = {'as_of': args.as_of.isoformat(), 'news': len(events), 'companies': len(dataset.rows),
        'classification_before': old['summary']['classification'],
        'classification_after': {'success': sum('result' in row for row in classifications), 'failed': sum('result' not in row for row in classifications),
            'topics': dict(Counter(topic for row in classifications if 'result' in row for topic in row['result']['topics']))},
        'okved_covered_before': sum(any(code.split('.')[0] in {'24','25','26','29','41','42','43','47','49','52','64','66','35'}
            for code in dataset.profile(cid).okved_codes) for cid in dataset.rows),
        'okved_covered_after': sum(bool(industry_topics(dataset.profile(cid))) for cid in dataset.rows),
        'known_model_positive_pairs': len(old_positive), 'found_before_top5': len(found_before), 'found_after_top5': len(found_after),
        'retrieval_comparison': comparisons, 'analyses_success': sum('result' in row for row in analyses), 'analyses_planned': len(analysis_cases()),
        'model_attempts': len(metrics), 'statuses': dict(Counter(metric['status'] for metric in metrics)),
        'reported_cost_usd': round(sum((metric.get('usage') or {}).get('cost', 0) or 0 for metric in metrics), 6),
        'per_model': {model: {'attempts': sum(metric['model'] == model for metric in metrics),
            'cost_usd': round(sum((metric.get('usage') or {}).get('cost', 0) or 0 for metric in metrics if metric['model'] == model), 6)} for model in sorted({metric['model'] for metric in metrics})},
        'limitations': ['Оценки 64 пар заморожены из исходного диагностического прогона; это не независимая разметка.',
            'Новые кандидаты без старой оценки не считались ни правильными, ни ошибочными. Precision/recall всего потока не измерялись.',
            'Участие отрасли контрагента не доказывает роль покупателя/поставщика и текущий эффект.',
            'Дословные цитаты и summary из claims не гарантируют смысловую корректность самих claims.',
            'Банковский корпус не загружен, этот источник по-прежнему недоступен.']}
    args.report_dir.mkdir(parents=True, exist_ok=True)
    shared_path = args.report_dir / 'shared-company-check.json'
    shared = read(shared_path) if shared_path.exists() else None
    agent_path = args.report_dir / 'shared-agent-check.json'
    shared_agent = read(agent_path) if agent_path.exists() else None
    save(args.report_dir / 'comparison.json', {'summary': summary, 'matches': matches, 'analyses': analyses,
        'summary_corrections': correction, 'shared_company_integration': shared, 'shared_agent': shared_agent})
    save(args.report_dir / 'summary.json', summary)
    from improvement_report import render
    (args.report_dir / 'report.html').write_text(render(summary, matches, analyses, correction, events, old,
        shared=shared, shared_agent=shared_agent), encoding='utf-8')
    lines = ['# Улучшение сопоставления новостей и компаний', '',
        f"На одном корпусе: {len(events)} новостей и {len(dataset.rows)} компаний; as_of={args.as_of.isoformat()}.", '',
        f"- Валидные классификации: {old['summary']['classification']['success']} → {summary['classification_after']['success']} из {len(events)}.",
        f"- Покрытие ОКВЭД: 2 → {summary['okved_covered_after']} компаний из 12.",
        f"- В top-5 найдено ранее модельно положительных пар: {len(found_before)} → {len(found_after)} из {len(old_positive)}. Это диагностическая метрика на замороженных оценках, не precision/recall.",
        f"- Повторено полных разборов: {summary['analyses_success']}/{summary['analyses_planned']}.",
        f"- Новый прогон: {len(metrics)} попыток, стоимость по ответам шлюза ${summary['reported_cost_usd']:.4f}.", '',
        'Цитаты выбираются по номерам фрагментов и подставляются кодом. Неизвестные ID и изменённые цитаты отклоняются. Summary собирается из принятых claims; известное смешение выручки и депозитов в summary устранено.', '',
        'Поиск использует короткие запросы по виду деятельности, отдельную ветку ключевой ставки и отдельные отрасли контрагентов. Ключевые слова и E5 объединяются по рангам. Смысловое сходство без лексического основания не выдаётся как сопоставление компании. Повторы публикаций удаляются по близости заголовка и текста.', '',
        'Доступен CLI research/ai/match_company.py --company-id U_128194 --dataset docs/companies/companies_analytics.json; NEWS_DATABASE_URL и NEWS_SEARCH_MODE=hybrid задаются окружением.', '',
        '## Ограничения', ''] + ['- ' + line for line in summary['limitations']]
    if shared:
        lines += ['', '## Компании и их эмбеддинги', '',
            f"В отдельной исследовательской БД: {shared['counts']['companies']} компаний и {shared['counts']['company_vectors']} векторов; исходные 153 новости и их векторы сохранены.", '',
            'Локальная E5 использует тот же model/revision и размерность 384 для новостей и компаний, но отдельные правила подготовки текста и profile_id. Новость кодируется как query, профиль компании — как passage. Это выдача кандидатов, а не оценка влияния.', '',
            'Профиль и платежные агрегаты читаются агентом из новых таблиц. Проверены SELECT-права и исключение снимков компаний, импортированных после as_of. Повторный импорт неизменённых данных сохраняет imported_at. Исторических версий компании нет.', '',
            'Этот контроль проведён после импорта компаний и отделён от парного сравнения со старым as_of. Файл shared-company-check.json содержит параметры и примеры обратного поиска.']
    if shared_agent:
        lines += ['', f"Полный запуск через общую БД: {shared_agent['company_id']}, статус {shared_agent['result']['status']}; источников {len(shared_agent['retrieved_sources'])}. Цитаты повторно проверены кодом; подробности в shared-agent-check.json."]
    (args.report_dir / 'findings.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['retrieval', 'analyze', 'report'])
    parser.add_argument('--baseline', type=Path, default=ROOT / 'research/ai/live_results/dataset-20261022')
    parser.add_argument('--output', type=Path, default=ROOT / 'research/ai/live_results/dataset-final-20261022')
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'research/evaluation/2026-10-22-improved')
    args = parser.parse_args()
    load_environment()
    old = baseline_snapshot()
    args.as_of = timestamp(old['summary']['manifest']['as_of'])
    dataset = CompanyDataset(ROOT / 'docs/companies/companies_analytics.json')
    reader = NewsReader.from_env()
    events = [NewsEvent.model_validate(event) for event in old['events']]
    if hashlib.sha256((ROOT / 'docs/companies/companies_analytics.json').read_bytes()).hexdigest() != old['summary']['manifest']['dataset_sha256']:
        raise ValueError('Company dataset changed; a paired comparison requires the frozen input')
    if (args.output / 'corpus.json').exists():
        expected = sorted([event.model_dump() for event in events], key=lambda e: e['id'])
        actual = sorted(read(args.output / 'corpus.json'), key=lambda e: e['id'])
        if expected != actual:
            raise ValueError('News corpus changed; baseline comparison would be invalid')
    globals()[args.phase](args, dataset, reader, events)


if __name__ == '__main__': main()
