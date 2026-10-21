"""Export the current AI contracts and the proposed T01 component boundaries."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / 'ai'))
from contracts import CompanyProfile, NewsEvent, Insight  # noqa: E402
from tasks import NewsPreparation  # noqa: E402

DRAFT = 'https://json-schema.org/draft/2020-12/schema'
S = {'type': 'string', 'minLength': 1}
TIME = {'type': 'string', 'format': 'date-time'}
def nullable(value): return {'anyOf': [value, {'type': 'null'}]}
def array(value, **extra): return {'type': 'array', 'items': value, **extra}
def obj(fields, **extra): return {'type': 'object', 'additionalProperties': False, 'properties': fields, 'required': list(fields), **extra}
def ref(name): return {'$ref': name + '.schema.json'}
def write(name, value):
    (ROOT / (name + '.schema.json')).write_text(json.dumps({'$schema': DRAFT, **value}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def main():
    for name, model in [('ai-company-profile', CompanyProfile), ('ai-news-event', NewsEvent), ('ai-insight', Insight)]:
        write(name, model.model_json_schema())
    write('analysis-request', obj({'contract_version': {'const': 't01-draft-1'}, 'request_id': S, 'company': ref('ai-company-profile'), 'news_id': S, 'events': array(ref('ai-news-event'), minItems=1), 'as_of': TIME, 'question': nullable(S)}))
    write('llm-input', obj({'company_id': S, 'news_id': S, 'profile_provenance': {'enum': ['synthetic_demo', 'dataset']}, 'sources': {'type': 'object', 'additionalProperties': S, 'minProperties': 1}, 'question': nullable(S), 'history': array(ref('ai-insight'), maxItems=4), 'schema': {'type': 'object'}}))
    write('news-preparation', NewsPreparation.model_json_schema())
    llm_input = json.loads((ROOT / 'llm-input.schema.json').read_text(encoding='utf-8'))
    llm_input['properties']['preparation'] = ref('news-preparation')
    write('llm-input', llm_input)
    write('ranking-result', obj({'company_id': S, 'news_id': S, 'score': {'type': 'integer', 'minimum': 0, 'maximum': 100}, 'eligible': {'type': 'boolean'}, 'reasons': array({'anyOf': [S, obj({'feature': S, 'weight': {'type': 'number'}, 'matched': array(S), 'limitation': nullable(S)})]}), 'missing_data': array(S)}))
    # Rank reasons are emitted by existing code with optional matched/limitation fields.
    rank = json.loads((ROOT / 'ranking-result.schema.json').read_text(encoding='utf-8'))
    rank['properties']['reasons']['items']['anyOf'][1]['required'] = ['feature', 'weight']
    write('ranking-result', rank)
    write('bank-context', obj({'contract_version': {'const': 't01-draft-1'}, 'sources': array({'$ref': '../common.schema.json#/$defs/source'}), 'bank': {'$ref': '../common.schema.json#/$defs/bank'}}))
    write('impact-assessment', obj({'contract_version': {'const': 't01-draft-1'}, 'company_id': S, 'news_id': S, 'importance': {'enum': ['high', 'medium', 'low']}, 'reason': S, 'method': {'enum': ['rules', 'classifier', 'editorial']}, 'is_demo': {'type': 'boolean'}, 'evidence': array(obj({'source_id': S, 'quote': S}), minItems=1)}))
    write('ux-enrichment', obj({'contract_version': {'const': 't01-draft-1'}, 'company_id': S, 'news_id': S, 'producer': S, 'is_demo': {'type': 'boolean'}, 'consequences': array({'$ref': '../common.schema.json#/$defs/claim'}), 'horizon': nullable(S), 'risks': array({'$ref': '../common.schema.json#/$defs/claim'}), 'risks_note': nullable(S), 'opportunities': array({'$ref': '../common.schema.json#/$defs/claim'}), 'opportunities_note': nullable(S), 'quantitative_estimate': nullable({'$ref': '../common.schema.json#/$defs/estimate'}), 'checks': array({'$ref': '../insight.schema.json#/properties/checks/items'}, minItems=1, maxItems=3), 'suggested_questions': array(S, minItems=2, maxItems=3), 'missing_data': array(S), 'limitations': array(S)}))
    write('assembly-request', obj({'contract_version': {'const': 't01-draft-1'}, 'company': ref('ai-company-profile'), 'event': ref('ai-news-event'), 'ai_insight': ref('ai-insight'), 'impact': ref('impact-assessment'), 'metadata': obj({'company_label': S, 'profile_version': S, 'profile_as_of': nullable(TIME), 'insight_id': S, 'insight_version': S, 'analyzed_at': TIME, 'collected_at': TIME, 'publisher': nullable(S), 'is_fictional_event': {'type': 'boolean'}, 'analysis_mode': {'enum': ['offline_baseline', 'live']}}), 'presentation': obj({'effect_title': S, 'event_summary': S, 'origin': {'enum': ['editorial_draft', 'demo_fixture', 'presentation_module']}}), 'bank_context': nullable(ref('bank-context')), 'enrichment': nullable(ref('ux-enrichment'))}))
    write('ux-bundle', obj({'contract_version': {'const': 't01-draft-1'}, 'company': {'$ref': '../company-profile.schema.json'}, 'event': {'$ref': '../news-event.schema.json'}, 'insight': {'$ref': '../insight.schema.json'}, 'feed_card': {'$ref': '../feed-card.schema.json'}, 'ai_insight': ref('ai-insight')}))
    write('chat-request', obj({'contract_version': {'const': 't01-draft-1'}, 'request_id': S, 'conversation_id': S, 'company_id': S, 'event_id': S, 'insight_version': S, 'context': {'$ref': '../chat-context.schema.json'}, 'message': obj({'message_id': S, 'text': S, 'created_at': TIME})}))
    for name in ('impact-assessment', 'ux-enrichment', 'bank-context'):
        value = json.loads((ROOT / (name + '.schema.json')).read_text(encoding='utf-8'))
        for key in ('company_id', 'news_id', 'profile_version'):
            value['properties'][key] = S
            if key not in value['required']:
                value['required'].append(key)
        write(name, value)
    print('Exported T01 schemas; AI models were not modified.')

if __name__ == '__main__':
    main()
