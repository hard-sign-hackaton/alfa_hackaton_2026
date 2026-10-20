"""Validate local JSON schemas, examples, references and negative cases. No network."""
import copy
import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent
BASE = ROOT.as_uri() + '/'

def load(path):
    return json.loads(path.read_text(encoding='utf-8'))

schemas = {p.name: load(p) for p in ROOT.glob('*.schema.json')}
registry = Registry().with_resources((BASE + name, Resource.from_contents(value)) for name, value in schemas.items())

def validate_shape(data, name):
    # Root $id supplies the base for relative refs; it is not an external endpoint.
    schema = {'$id': BASE + name, **schemas[name]}
    Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(data)

def require(condition, message):
    if not condition:
        raise ValueError(message)

def claims_in(value):
    if isinstance(value, dict):
        if {'id', 'kind', 'evidence', 'feature_ids'}.issubset(value):
            yield value
        for child in value.values():
            yield from claims_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from claims_in(child)

def check_claims(value, sources, features):
    by_id = {s['id']: s for s in sources}
    require(len(by_id) == len(sources), 'Duplicate source id')
    for source in sources:
        ids = [f['id'] for f in source['fragments']]
        require(len(ids) == len(set(ids)), 'Duplicate fragment id')
    for claim in claims_in(value):
        require(set(claim['feature_ids']) <= features, 'Unknown feature reference')
        for evidence in claim['evidence']:
            require(evidence['source_id'] in by_id, 'Unknown source reference')
            source = by_id[evidence['source_id']]
            require(evidence['fragment_id'] in {f['id'] for f in source['fragments']}, 'Unknown fragment reference')
            if claim['kind'] == 'bank_position':
                require(source['kind'] == 'bank', 'Bank position requires bank source')
    return by_id

def semantic(data, name, company=None):
    if name == 'company-profile':
        ids = [f['id'] for f in data['features']]
        require(len(ids) == len(set(ids)), 'Duplicate company feature id')
    elif name == 'news-event':
        check_claims(data['facts'], data['sources'], set())
    elif name == 'insight':
        require(company is not None, 'Company required to check insight')
        require(data['company_id'] == company['company_id'], 'Wrong company')
        require(data['profile_version'] == company['profile_version'], 'Wrong profile version')
        sources = check_claims(data, data['sources'], {f['id'] for f in company['features']})
        bank = data['bank']
        for source_id in bank['source_ids']:
            require(source_id in sources and sources[source_id]['kind'] == 'bank', 'Invalid bank source')
        if bank['position'] is not None:
            require(bank['position']['kind'] == 'bank_position', 'Wrong bank claim kind')
            require({e['source_id'] for e in bank['position']['evidence']} <= set(bank['source_ids']), 'Bank evidence outside bank source list')
        if bank['interpretation'] is not None:
            require(bank['interpretation']['kind'] == 'ai_inference', 'Bank interpretation must be AI inference')
    elif name == 'chat-context':
        snap = data['context_snapshot']
        semantic(snap['company'], 'company-profile')
        semantic(snap['event'], 'news-event')
        semantic(snap['insight'], 'insight', snap['company'])
        require(data['company_id'] == snap['company']['company_id'] == snap['insight']['company_id'], 'Mixed companies')
        require(data['event_id'] == snap['event']['event_id'] == snap['insight']['event_id'], 'Mixed events')
        require(data['insight_version'] == snap['insight']['insight_version'], 'Wrong insight version')
        messages = {m['message_id']: m for m in data['messages']}
        require(len(messages) == len(data['messages']), 'Duplicate message id')
        features = {f['id'] for f in snap['company']['features']}
        for item in data['user_clarifications']:
            require(item['message_id'] in messages and messages[item['message_id']]['role'] == 'user', 'Clarification requires user message')
            require(item['feature']['provenance']['kind'] == 'user', 'Clarification must be attributed to user')
            features.add(item['feature']['id'])
        check_claims(data['messages'], snap['insight']['sources'], features)
        for message in messages.values():
            retry_of = message['retry_of']
            require(retry_of is None or retry_of in messages and retry_of != message['message_id'], 'Invalid retry reference')
    # Validate timestamps even if optional RFC3339 format extras are not installed.
    def dates(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if (key.endswith('_at') or key in ('timestamp', 'profile_as_of', 'as_of')) and child is not None:
                    require(datetime.fromisoformat(child.replace('Z', '+00:00')).tzinfo is not None, 'Timestamp must have timezone')
                dates(child)
        elif isinstance(value, list):
            for child in value:
                dates(child)
    dates(data)

def main():
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    company = load(ROOT / 'examples/company-profile.json')
    examples = {}
    for path in sorted((ROOT / 'examples').glob('*.json')):
        name = 'insight' if path.stem == 'insight-partial' else path.stem
        data = load(path)
        validate_shape(data, name + '.schema.json')
        semantic(data, name, company)
        examples[path.stem] = data
        print('PASS', path.name)
    card = examples['feed-card']
    insight = examples['insight']
    event = examples['news-event']
    require(all(card[k] == insight[k] for k in ('company_id', 'profile_version', 'event_id', 'insight_id', 'insight_version', 'importance', 'effect_title')), 'Feed/insight mismatch')
    require(card['event_id'] == event['event_id'] and card['source_id'] in {s['id'] for s in event['sources']}, 'Feed/event mismatch')
    negatives = []
    def invalid(name, original, mutate):
        data = copy.deepcopy(original)
        mutate(data)
        negatives.append((name, data))
    invalid('feed-card', card, lambda d: d.update(importance='urgent'))
    invalid('feed-card', card, lambda d: d.pop('company_id'))
    invalid('company-profile', company, lambda d: d['features'][0].update(value=None))
    invalid('insight', insight, lambda d: d['bank'].update(position=None))
    invalid('insight', insight, lambda d: d['conclusion']['evidence'][0].update(source_id='missing'))
    invalid('insight', insight, lambda d: d['bank']['position'].update(kind='ai_inference'))
    invalid('chat-context', examples['chat-context'], lambda d: d.update(company_id='another-company'))
    invalid('chat-context', examples['chat-context'], lambda d: d['user_clarifications'][0].update(message_id='missing'))
    for name, data in negatives:
        try:
            validate_shape(data, name + '.schema.json')
            semantic(data, name, company)
        except Exception as error:
            require(type(error).__name__ in ('ValidationError', 'ValueError'), 'Unexpected validation failure: ' + repr(error))
        else:
            raise AssertionError('Invalid example accepted: ' + name)
    print(f'PASS {len(schemas)} schemas, {len(examples)} examples, cross-object links, {len(negatives)} negative cases')

if __name__ == '__main__':
    main()
