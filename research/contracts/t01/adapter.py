"""Offline boundary adapter: existing AI objects -> existing U01 UX objects.

No LLM, network, storage or implicit importance assignment. This is a draft
integration example, not the application backend or a production pipeline.
"""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / 'ai'))
from contracts import CompanyProfile, NewsEvent, Insight, evidence_sources, validate_evidence  # noqa: E402
from retrieval import source_registry  # noqa: E402

def adapt(request):
    # Caller validates the envelope against assembly-request.schema.json first.
    company = CompanyProfile.model_validate(request['company'])
    event = NewsEvent.model_validate(request['event'])
    result = Insight.model_validate(request['ai_insight'])
    retrieved = source_registry(request.get('retrieved_sources'), company, event,
                                as_of=request['metadata']['analyzed_at'])
    validate_evidence(result, company, event, list(retrieved.values()))
    m, p, impact = request['metadata'], request['presentation'], request['impact']
    for component in ('impact', 'bank_context', 'enrichment'):
        payload = request[component]
        if payload is not None and (payload['company_id'] != company.id or payload['news_id'] != event.id or payload['profile_version'] != m['profile_version']):
            raise ValueError('Component context/version mismatch: ' + component)
    if impact['company_id'] != company.id or impact['news_id'] != event.id:
        raise ValueError('Impact assessment belongs to a different company/event')
    for evidence in impact['evidence']:
        bodies = evidence_sources(company, event)
        if evidence['source_id'] not in bodies or evidence['quote'] not in bodies[evidence['source_id']]:
            raise ValueError('Invalid impact evidence')
    p = {**p, 'importance': impact['importance'], 'importance_reason': impact['reason']}
    demo = company.provenance == 'synthetic_demo' or m['analysis_mode'] == 'offline_baseline' or p['origin'] == 'demo_fixture' or m['is_fictional_event']
    demo = demo or impact['is_demo']
    demo = demo or any(value.is_demo for value in retrieved.values())
    bank_context = request['bank_context']
    if bank_context and any(s['is_fictional'] for s in bank_context['sources']):
        demo = True
    raw_sources = evidence_sources(company, event, list(retrieved.values()))
    source_map = {}
    def source(source_id):
        if source_id not in source_map:
            if source_id in retrieved:
                value = retrieved[source_id]
                source_map[source_id] = {'id': source_id, 'kind': 'company' if value.kind == 'metric' else value.kind,
                                         'title': value.title, 'publisher': None, 'url': value.url,
                                         'locator': value.locator, 'published_at': value.published_at,
                                         'retrieved_at': m['analyzed_at'], 'forecast_period': None,
                                         'is_fictional': value.is_demo, 'availability': 'available', 'fragments': []}
                return source_map[source_id]
            is_news = source_id == f'news:{event.id}'
            source_map[source_id] = {'id': source_id, 'kind': 'news' if is_news else 'company', 'title': event.title if is_news else f'Признак компании: {source_id.rsplit(":", 1)[-1]}', 'publisher': m['publisher'] if is_news else None, 'url': event.url if is_news else None, 'locator': event.url if is_news else company.source_ref + '#' + source_id.rsplit(':', 1)[-1], 'published_at': event.published_at if is_news else m['profile_as_of'], 'retrieved_at': m['collected_at'] if is_news else m['analyzed_at'], 'forecast_period': None, 'is_fictional': m['is_fictional_event'] if is_news else company.provenance == 'synthetic_demo', 'availability': 'available', 'fragments': []}
        return source_map[source_id]
    features = []
    for name, value in company.model_dump().items():
        if name in ('id', 'provenance', 'source_ref'):
            continue
        # UI feature is a scalar display value; the original typed array remains
        # in request.company and in exact quoted source fragments.
        display = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
        features.append({'id': name, 'label': name, 'value': display, 'unit': 'RUB' if name == 'annual_revenue_rub' else None, 'period': None, 'status': 'unknown' if value is None or value == [] else 'known', 'provenance': {'kind': 'demo' if company.provenance == 'synthetic_demo' else 'company_dataset', 'locator': company.source_ref + '#' + name, 'as_of': m['profile_as_of']}})
        if features[-1]['status'] == 'unknown':
            features[-1]['value'] = None
    limitations = ['Заголовок и суть события подготовлены слоем представления; важность поступает отдельно от классификатора. Ранжирование не определяет важность.', 'Год выручки и дата исходного профиля могут быть неизвестны.']
    if demo:
        limitations.append('Демонстрационные данные или offline-анализ; не проверенный результат работы LLM.')
    converted = []
    for i, claim in enumerate(result.claims):
        refs, feature_ids = [], []
        for evidence in claim.evidence:
            body = raw_sources[evidence.source_id]
            start = body.index(evidence.quote)
            fragment_id = 'quote-' + hashlib.sha256(evidence.quote.encode()).hexdigest()[:16]
            s = source(evidence.source_id)
            if not any(f['id'] == fragment_id for f in s['fragments']):
                s['fragments'].append({'id': fragment_id, 'text': evidence.quote, 'locator': f'characters:{start}:{start + len(evidence.quote)}'})
            refs.append({'source_id': s['id'], 'fragment_id': fragment_id})
            if evidence.source_id.startswith(f'company:{company.id}:'):
                feature_ids.append(evidence.source_id.rsplit(':', 1)[-1])
        converted.append({'id': f'{m["insight_id"]}:claim:{i+1}', 'text': claim.text, 'kind': 'source_fact' if claim.kind == 'fact' else 'ai_inference', 'evidence': refs, 'feature_ids': sorted(set(feature_ids)), 'assumptions': [], 'limitations': ['Наличие цитаты не доказывает логическое следование вывода.'] if claim.kind == 'hypothesis' else []})
    news_source = source(f'news:{event.id}')
    # Preserve the original title as an attributed source claim even if the AI
    # returned no news fact. Never label the AI summary as an independent fact.
    title_fragment = {'id': 'title', 'text': event.title, 'locator': 'title'}
    news_source['fragments'].append(title_fragment)
    title_claim = {'id': m['insight_id'] + ':event-title', 'text': event.title, 'kind': 'source_fact', 'evidence': [{'source_id': news_source['id'], 'fragment_id': 'title'}], 'feature_ids': [], 'assumptions': [], 'limitations': ['Заголовок источника; прогноз не становится фактом будущего.']}
    hypotheses = [c for c in converted if c['kind'] == 'ai_inference']
    all_refs = [e for c in converted for e in c['evidence']]
    conclusion = {'id': m['insight_id'] + ':summary', 'text': result.summary, 'kind': 'ai_inference', 'evidence': list({(e['source_id'], e['fragment_id']): e for e in all_refs}.values()), 'feature_ids': sorted({f for c in converted for f in c['feature_ids']}), 'assumptions': [], 'limitations': ['Резюме исходного AI-ответа; логическое следование требует отдельной проверки.']}
    if bank_context:
        existing = set(source_map)
        if existing.intersection(s['id'] for s in bank_context['sources']):
            raise ValueError('Bank context source IDs collide with AI sources')
        if any(s['kind'] != 'bank' for s in bank_context['sources']):
            raise ValueError('Bank context must contain bank sources only')
        bank = copy.deepcopy(bank_context['bank'])
        bank_sources = copy.deepcopy(bank_context['sources'])
        limitations.append('Материал банка передан отдельно и не входил в контекст текущего AI-вызова; общая интерпретация с ним не пересчитывалась.')
    elif any(value.kind == 'bank' for value in retrieved.values()):
        bank_values = [value for value in retrieved.values() if value.kind == 'bank']
        value = bank_values[0]
        quote = value.text[:500]
        bank_source = source(value.source_id)
        bank_source['fragments'].append({'id': 'bank-excerpt', 'text': quote, 'locator': f'characters:0:{len(quote)}'})
        position = {'id': m['insight_id'] + ':bank-excerpt', 'text': 'Фрагмент найденного материала банка: ' + quote,
                    'kind': 'bank_position', 'evidence': [{'source_id': value.source_id, 'fragment_id': 'bank-excerpt'}],
                    'feature_ids': [], 'assumptions': [], 'limitations': ['Цитата отдельного материала; не консолидированная позиция банка.']}
        bank = {'status': 'found', 'position': position, 'interpretation': None,
                'source_ids': [value.source_id], 'note': 'Найденный фрагмент входил в контекст анализа; отдельная интерпретация позиции не выделена.'}
        bank_sources = []
    else:
        note = ('Подтверждённые материалы банка не переданы в контекст; статус поиска отдельно не указан.'
                if 'retrieved_sources' in request else
                'Поиск и передача аналитики банка в текущем AI-процессе не реализованы. Это не результат поиска not_found.')
        bank = {'status': 'unavailable', 'position': None, 'interpretation': None, 'source_ids': [], 'note': note}
        bank_sources = []
    ux_company = {'schema_version': '0.1.0', 'company_id': company.id, 'company_label': m['company_label'], 'profile_version': m['profile_version'], 'profile_as_of': m['profile_as_of'], 'is_demo': company.provenance == 'synthetic_demo', 'features': features, 'limitations': ['Дата и период выручки не восстановлены из отсутствующих данных.']}
    ux_event = {'schema_version': '0.1.0', 'event_id': event.id, 'original_title': event.title, 'text': event.text, 'summary': p['event_summary'], 'published_at': event.published_at, 'collected_at': m['collected_at'], 'is_fictional': m['is_fictional_event'], 'sources': [news_source], 'facts': [title_claim], 'limitations': ['Суть события предоставлена редакционным слоем.']}
    missing = list(result.missing_data)
    if request['enrichment'] is None:
        missing.append('Дополнительные блоки от модуля обогащения еще не переданы.')
    if bank_context is None and not any(value.kind == 'bank' for value in retrieved.values()):
        missing.append('Нет подтверждённого материала банка в контексте анализа.' if 'retrieved_sources' in request
                       else 'Модуль банковских материалов еще не подключен.')
    ux_insight = {'schema_version': '0.1.0', 'insight_id': m['insight_id'], 'insight_version': m['insight_version'], 'company_id': company.id, 'profile_version': m['profile_version'], 'event_id': event.id, 'content_status': 'partial', 'analyzed_at': m['analyzed_at'], 'is_demo': demo, 'effect_title': p['effect_title'], 'importance': p['importance'], 'importance_reason': p['importance_reason'], 'conclusion': conclusion, 'event_facts': [title_claim] + [c for c in converted if c['kind'] == 'source_fact'], 'relevance_reasons': [{'feature_ids': c['feature_ids'], 'explanation': c['text']} for c in hypotheses if c['feature_ids']], 'consequences': hypotheses, 'horizon': None, 'risks': [], 'risks_note': 'Отдельные риски не выделены текущим AI-контрактом.', 'opportunities': [], 'opportunities_note': 'Отдельные возможности не выделены текущим AI-контрактом.', 'quantitative_estimate': None, 'missing_data': missing, 'bank': bank, 'checks': [{'text': 'Уточнить недостающие сведения.', 'purpose': 'Проверить применимость вывода к компании.', 'required_data': missing}], 'suggested_questions': ['Каких данных не хватает для оценки эффекта?', 'Какие основания у этого вывода?'], 'sources': list(source_map.values()) + bank_sources, 'limitations': limitations, 'trace': [{'id': m['insight_id'] + ':projection', 'timestamp': m['analyzed_at'], 'action': 'Преобразовать проверенный AI-ответ в UX-представление', 'tool': 't01.adapter', 'input_ids': [company.id, event.id], 'output_ids': [m['insight_id']], 'result_summary': 'Проверены ID и наличие точных цитат; неполные блоки явно обозначены.', 'status': 'partial', 'checks': ['Pydantic contracts', 'validate_evidence'], 'correction': 'Не назначать важность по score и не придумывать недостающие блоки.'}]}
    enrichment = request['enrichment']
    if enrichment is not None:
        if enrichment['company_id'] != company.id or enrichment['news_id'] != event.id:
            raise ValueError('Enrichment belongs to a different company/event')
        for key in ('consequences', 'horizon', 'risks', 'risks_note', 'opportunities', 'opportunities_note', 'quantitative_estimate', 'checks', 'suggested_questions'):
            ux_insight[key] = copy.deepcopy(enrichment[key])
        ux_insight['missing_data'] = list(dict.fromkeys(missing + enrichment['missing_data']))
        ux_insight['limitations'].extend(enrichment['limitations'])
        ux_insight['is_demo'] = ux_insight['is_demo'] or enrichment['is_demo']
    # This draft adapter does not perform the final semantic/completeness check:
    # only that future module may promote the assembled document to ready.
    ux_insight['limitations'].append('Финальная проверка полноты и смысла еще не выполнена; partial не означает конфликт контрактов.')
    feed = {k: ux_insight[k] for k in ('schema_version', 'company_id', 'profile_version', 'event_id', 'insight_id', 'insight_version', 'content_status', 'effect_title', 'importance', 'analyzed_at', 'is_demo', 'limitations')}
    feed.update({'event_summary': p['event_summary'], 'publisher': m['publisher'], 'published_at': event.published_at, 'source_id': news_source['id'], 'source_url': event.url})
    return {'contract_version': 't01-draft-1', 'company': ux_company, 'event': ux_event, 'insight': ux_insight, 'feed_card': feed, 'ai_insight': result.model_dump()}

if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python adapter.py assembly-request.json ux-bundle.json')
    from verify import validate_request, validate_bundle
    data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    validate_request(data)
    bundle = adapt(data)
    validate_bundle(bundle)
    Path(sys.argv[2]).write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
