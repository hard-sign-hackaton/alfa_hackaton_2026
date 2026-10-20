"""Run relevance scoring and company-specific publication analysis."""
import argparse
from datetime import datetime
import json
from pathlib import Path

from agent import ResearchAgent
from contracts import CompanyProfile, Insight
from fixtures import BASE, news, profiles, relevance_labels
from provider import DeepSeekClient, ModelError
from ranking import rank_pair

AS_OF = datetime.fromisoformat('2026-10-20T17:00:00+00:00')
QUESTION = 'Какие данные нужны, чтобы оценить влияние этой новости на нашу выручку?'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(mode, output):
    companies, events = profiles(), news()
    labels = relevance_labels(companies, events)
    write(output / 'company_profiles.json', [c.model_dump() for c in companies])
    write(output / 'insight.schema.json', Insight.model_json_schema())
    write(output / 'company_profile.schema.json', CompanyProfile.model_json_schema())
    pairs = []
    for company in companies:
        for event in events:
            item = rank_pair(company, event, as_of=AS_OF)
            item['expected_relevant'] = bool(labels[company.id, event.id])
            item['predicted_relevant'] = item['score'] >= 50
            pairs.append(item)
    write(output / 'ranking_8_pairs.json', {
        'mode': 'offline_rule_baseline', 'as_of': AS_OF.isoformat(),
        'profiles_are_synthetic': True, 'news_ids': [n.id for n in events], 'pairs': pairs,
        'correct_on_curated_examples': sum(p['expected_relevant'] == p['predicted_relevant'] for p in pairs),
        'total': len(pairs), 'limitation': 'Small manually labeled sample',
    })
    # Additional ranking error cases.
    electronics = companies[0].model_copy(update={'id': 'stress-electronics', 'okved_codes': ['26.11'],
                                                 'okved_names': ['Производство электронных компонентов']})
    write(output / 'ranking_error_cases.json', [
        {'case': 'retailer_does_not_sell_on_marketplaces',
         'mode': 'synthetic_stress_case',
         'rank': rank_pair(companies[1], events[1], as_of=AS_OF),
         'expected_relevant': False, 'error': 'false_positive',
         'reason': 'Retail OKVED does not establish marketplace sales; sales channel is unknown'},
        {'case': 'electronics_depends_on_steel_customer',
         'mode': 'synthetic_stress_case',
         'rank': rank_pair(electronics, events[0], as_of=AS_OF),
         'expected_relevant': True, 'error': 'false_negative',
         'reason': 'Synthetic customer dependency is absent from the profile'},
    ])
    client = DeepSeekClient() if mode == 'live' else None
    if client and not client.api_key:
        raise ModelError('DEEPSEEK_API_KEY is required for live mode')
    results = []
    try:
        for company in companies:
            agent = ResearchAgent(companies, events, client=client, as_of=AS_OF,
                                  checkpoint=output / (company.id + '.checkpoint.json'))
            results.append(agent.run(company.id, events[0].id, question=QUESTION))
    finally:
        if client:
            write(output / 'live_telemetry.json', {'mode': 'live', 'calls': client.telemetry,
                                                 'contains_mock_data': False})
    write(output / 'shared_news_interpretations.json', results)
    write(output / 'summary.json', {
        'mode': mode,
        'companies': len(companies),
        'publications': len(events),
        'ranked_pairs': len(pairs),
        'profile_provenance': 'synthetic_demo',
        'payment_data_available': False,
    })


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['offline', 'live'], default='offline')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    destination = args.output or BASE / ('live_results' if args.mode == 'live' else 'results')
    try:
        run(args.mode, destination)
    except ModelError as exc:
        parser.exit(2, str(exc) + '\n')
    print('Results: ' + str(destination))
