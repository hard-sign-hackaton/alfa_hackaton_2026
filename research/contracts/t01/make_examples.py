"""Reproduce bridge fixtures from saved offline research, without LLM calls."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / 'ai'))
from fixtures import profiles, news
from adapter import adapt, evidence_sources, Insight

def load(p): return json.loads(p.read_text(encoding='utf-8'))
def save(name, data):
    (ROOT / 'examples').mkdir(exist_ok=True)
    (ROOT / 'examples' / (name + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def main():
    company, event = profiles()[0], news()[0]
    checkpoint = load(ROOT.parents[1] / 'ai/results/demo-metal.checkpoint.json')
    raw = load(ROOT.parents[1] / 'news/news_examples.json')
    saved_event = next(e for e in raw if e['id'] == event.id)
    now = '2026-10-20T17:00:00+00:00'
    request = {'contract_version': 't01-draft-1', 'company': company.model_dump(), 'event': event.model_dump(), 'ai_insight': checkpoint['result'], 'metadata': {'company_label': 'Тестовая металлургическая компания', 'profile_version': 'fixture-v1', 'profile_as_of': None, 'insight_id': 't01-demo-metal', 'insight_version': 'projection-v1', 'analyzed_at': now, 'collected_at': saved_event['collected_at'], 'publisher': saved_event.get('source'), 'is_fictional_event': False, 'analysis_mode': 'offline_baseline'}, 'presentation': {'effect_title': 'Возможное давление на новые заказы', 'event_summary': 'Компания-источник пересмотрела прогноз спроса на сталь. Событие требует проверки применимости к вашему бизнесу.', 'origin': 'demo_fixture'}, 'impact': {'contract_version': 't01-draft-1', 'company_id': company.id, 'news_id': event.id, 'importance': 'high', 'reason': 'Демо-оценка: событие связано с основной отраслью компании; финансовый эффект не измерен.', 'method': 'editorial', 'is_demo': True, 'evidence': [{'source_id': 'news:' + event.id, 'quote': event.title}]}, 'bank_context': None, 'enrichment': None}
    request['impact']['profile_version'] = request['metadata']['profile_version']
    save('assembly-request', request)
    bundle = adapt(request)
    save('ux-bundle-request', bundle)
    rich = copy.deepcopy(request)
    prior = load(ROOT.parent / 'examples/insight.json')
    # The bank material is a visibly fictional test fixture, not real research.
    bank_source = copy.deepcopy(next(s for s in prior['sources'] if s['kind'] == 'bank'))
    bank_source.update({'id': 't01-demo-bank-steel', 'title': 'Промышленный спрос: сценарий IV квартала', 'locator': 'demo:t01-bank-steel', 'forecast_period': 'IV квартал 2026', 'fragments': [{'id': 'bank-steel-f1', 'text': 'В вымышленном обзоре предполагается неравномерная динамика промышленного спроса. Состав заказчиков важен для оценки отдельной компании.', 'locator': 'paragraph:1'}]})
    evidence = [{'source_id': bank_source['id'], 'fragment_id': 'bank-steel-f1'}]
    position = {'id': 't01-bank-position', 'text': bank_source['fragments'][0]['text'], 'kind': 'bank_position', 'evidence': evidence, 'feature_ids': [], 'assumptions': [], 'limitations': ['Вымышленный материал.']}
    interpretation = {'id': 't01-bank-interpretation', 'text': 'Материал предлагает проверить состав заказчиков, но не подтверждает изменение выручки компании.', 'kind': 'ai_inference', 'evidence': evidence, 'feature_ids': [], 'assumptions': [], 'limitations': ['Вымышленная демонстрационная интерпретация отдельного модуля.']}
    rich['bank_context'] = {'contract_version': 't01-draft-1', 'company_id': company.id, 'news_id': event.id, 'profile_version': request['metadata']['profile_version'], 'sources': [bank_source], 'bank': {'status': 'found', 'position': position, 'interpretation': interpretation, 'source_ids': [bank_source['id']], 'note': 'Вымышленный пример, не реальная позиция Альфа-Банка.'}}
    rich['enrichment'] = {'contract_version': 't01-draft-1', 'company_id': company.id, 'news_id': event.id, 'producer': 'demo-enrichment-fixture', 'is_demo': True, 'consequences': [], 'horizon': None, 'risks': [], 'risks_note': 'Демо-модуль не установил конкретные риски; это не означает их отсутствия.', 'opportunities': [], 'opportunities_note': 'Возможности требуют проверки на данных компании.', 'quantitative_estimate': None, 'checks': [{'text': 'Проверить структуру заказчиков и портфель заказов.', 'purpose': 'Установить связь рыночного сигнала с компанией.', 'required_data': ['Портфель заказов']}], 'suggested_questions': ['Как проверить влияние на новые заказы?', 'Какие данные о заказчиках нужны?'], 'missing_data': ['Структура заказчиков'], 'limitations': ['Ответ отдельного модуля смоделирован, не результат LLM или классификатора.']}
    rich['enrichment']['profile_version'] = request['metadata']['profile_version']
    save('assembly-with-enrichment', rich)
    save('ux-bundle-with-enrichment', adapt(rich))
    save('analysis-request', {'contract_version': 't01-draft-1', 'request_id': 't01-analysis-1', 'company': company.model_dump(), 'news_id': event.id, 'events': [e.model_dump() for e in news()], 'as_of': now, 'question': None})
    rank = next(s['result'] for s in checkpoint['trace'] if s['tool'] == 'rank')
    save('ranking-result', rank)
    save('llm-input', {'company_id': company.id, 'news_id': event.id, 'profile_provenance': company.provenance, 'sources': evidence_sources(company, event), 'question': None, 'history': [], 'schema': Insight.model_json_schema()})
    context = {'schema_version': '0.1.0', 'conversation_id': 't01-conversation-1', 'company_id': company.id, 'event_id': event.id, 'insight_version': bundle['insight']['insight_version'], 'is_demo': True, 'context_snapshot': {'snapshot_id': 't01-snapshot-1', 'created_at': now, 'company': bundle['company'], 'event': bundle['event'], 'insight': bundle['insight']}, 'messages': [], 'user_clarifications': []}
    save('chat-request', {'contract_version': 't01-draft-1', 'request_id': 't01-chat-request-1', 'conversation_id': context['conversation_id'], 'company_id': company.id, 'event_id': event.id, 'insight_version': bundle['insight']['insight_version'], 'context': context, 'message': {'message_id': 't01-message-1', 'text': 'Какие данные нужны для оценки влияния?', 'created_at': now}})
    print('Generated T01 examples from saved offline outputs; presentation/enrichment are explicit demo fixtures.')

if __name__ == '__main__':
    main()
