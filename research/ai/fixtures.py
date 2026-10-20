"""Synthetic company profiles for local experiments."""
import json
from pathlib import Path
from contracts import CompanyProfile, NewsEvent

BASE = Path(__file__).resolve().parent


def profiles():
    common = dict(provenance='synthetic_demo', source_ref='fixtures.py',
                  ownership_form='ООО', trade_countries=None, development_stage=None)
    return [
        CompanyProfile(id='demo-metal', okved_codes=['24.10'],
                       okved_names=['Производство чугуна, стали и ферросплавов'],
                       registration_region='Челябинская область', annual_revenue_rub=800_000_000.0,
                       banking_services=['credit', 'leasing'], **common),
        CompanyProfile(id='demo-retail', okved_codes=['47.91'],
                       okved_names=['Розничная торговля по почте или через Интернет'],
                       registration_region='Москва', annual_revenue_rub=120_000_000.0,
                       banking_services=['cash_register', 'payroll'], **common),
    ]


def news():
    raw = json.loads((BASE.parent / 'news' / 'news_examples.json').read_text(encoding='utf-8'))
    by_topic = {}
    for row in raw:
        for topic in row['topics']:
            by_topic.setdefault(topic, row)
    # Select one saved publication per topic.
    return [NewsEvent(**{key: by_topic[topic][key] for key in
                         ('id', 'title', 'text', 'url', 'published_at', 'topics')})
            for topic in ('metallurgy', 'retail_ecommerce', 'energy', 'financial_markets')]


def relevance_labels(companies, events):
    # Expected labels for the selected sample.
    return {(company.id, event.id): int(
        (company.id == 'demo-metal' and 'metallurgy' in event.topics)
        or (company.id == 'demo-retail' and 'retail_ecommerce' in event.topics))
        for company in companies for event in events}
