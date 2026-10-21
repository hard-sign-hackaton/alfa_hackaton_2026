"""Local validation of the T01 boundaries, legacy schemas and identity links."""
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent
CONTRACTS = ROOT.parent
spec = importlib.util.spec_from_file_location('ux_validator', CONTRACTS / 'validate.py')
ux = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ux)
from adapter import adapt, CompanyProfile, NewsEvent, Insight, validate_evidence
from retrieval import source_registry

def load(path): return json.loads(path.read_text(encoding='utf-8'))

def validator(path):
    resources = [(p.as_uri(), Resource.from_contents(load(p))) for p in list(CONTRACTS.glob('*.schema.json')) + list(ROOT.glob('*.schema.json'))]
    return Draft202012Validator({'$id': path.as_uri(), **load(path)}, registry=Registry().with_resources(resources), format_checker=FormatChecker())

def validate_request(data):
    validator(ROOT / 'assembly-request.schema.json').validate(data)
    company = CompanyProfile.model_validate(data['company'])
    event = NewsEvent.model_validate(data['event'])
    insight = Insight.model_validate(data['ai_insight'])
    retrieved = list(source_registry(data.get('retrieved_sources'), company, event,
                                    as_of=data['metadata']['analyzed_at']).values())
    validate_evidence(insight, company, event, retrieved)

def validate_bundle(bundle):
    validator(ROOT / 'ux-bundle.schema.json').validate(bundle)
    ux.semantic(bundle['company'], 'company-profile')
    ux.semantic(bundle['event'], 'news-event')
    ux.semantic(bundle['insight'], 'insight', bundle['company'])
    feed, insight, event = bundle['feed_card'], bundle['insight'], bundle['event']
    for key in ('company_id', 'profile_version', 'event_id', 'insight_id', 'insight_version', 'importance', 'effect_title', 'content_status'):
        if feed[key] != insight[key]:
            raise ValueError('Feed/insight mismatch: ' + key)
    if event['event_id'] != insight['event_id'] or bundle['ai_insight']['news_id'] != event['event_id'] or bundle['ai_insight']['company_id'] != insight['company_id']:
        raise ValueError('Mixed company/event context')

def validate_analysis_request(data):
    validator(ROOT / 'analysis-request.schema.json').validate(data)
    from datetime import datetime
    events = {e['id']: e for e in data['events']}
    if len(events) != len(data['events']) or data['news_id'] not in events:
        raise ValueError('Selected event missing or duplicate event IDs')
    as_of = datetime.fromisoformat(data['as_of'])
    published = datetime.fromisoformat(events[data['news_id']]['published_at'].replace('Z', '+00:00'))
    if not as_of.tzinfo or not published.tzinfo or published > as_of:
        raise ValueError('Unknown timezone or future publication')

def main():
    for path in ROOT.glob('*.schema.json'):
        Draft202012Validator.check_schema(load(path))
    examples = ROOT / 'examples'
    for stem in ('assembly-request', 'assembly-with-enrichment'):
        request = load(examples / (stem + '.json'))
        validate_request(request)
        bundle = adapt(request)
        validate_bundle(bundle)
        if bundle != load(examples / (stem.replace('assembly', 'ux-bundle') + '.json')):
            raise ValueError('Saved bundle differs from reproducible adapter output')
        print('PASS', stem, '-> ux-bundle; existing AI and UX schemas unchanged')
    validate_analysis_request(load(examples / 'analysis-request.json'))
    validator(ROOT / 'ranking-result.schema.json').validate(load(examples / 'ranking-result.json'))
    llm = load(examples / 'llm-input.json')
    validator(ROOT / 'llm-input.schema.json').validate(llm)
    if llm['schema'] != Insight.model_json_schema():
        raise ValueError('LLM output schema drift')
    chat = load(examples / 'chat-request.json')
    validator(ROOT / 'chat-request.schema.json').validate(chat)
    ux.semantic(chat['context'], 'chat-context')
    for key in ('company_id', 'event_id', 'insight_version', 'conversation_id'):
        if chat[key] != chat['context'][key]:
            raise ValueError('Chat context mismatch')
    print('PASS analysis, ranking and chat boundary examples')

if __name__ == '__main__':
    main()
