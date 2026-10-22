"""Topic and geographic relevance scoring."""
from datetime import datetime, timezone

OKVED_TOPICS = {
    '24': {'metallurgy'}, '25': {'metallurgy'},
    '26': {'electronics'}, '29': {'automotive'}, '45': {'automotive'},
    '46': {'wholesale_trade'}, '68': {'real_estate'},
    '41': {'construction'}, '42': {'construction'}, '43': {'construction'},
    '47': {'retail_ecommerce'}, '49': {'logistics'}, '52': {'logistics'},
    '64': {'financial_markets'}, '66': {'financial_markets'}, '35': {'energy'},
}
OKVED_SPECIALIZATIONS = {'46.43': {'electronics', 'wholesale_trade'}}


def industry_topics(profile):
    topics = set()
    for code in profile.okved_codes:
        topics.update(OKVED_TOPICS.get(code.split('.')[0], set()))
        for prefix, extra in OKVED_SPECIALIZATIONS.items():
            if code == prefix or code.startswith(prefix + '.'):
                topics.update(extra)
    return topics


def rank_pair(company, news, *, as_of):
    published = datetime.fromisoformat(news.published_at.replace('Z', '+00:00'))
    if as_of.tzinfo is None or published.tzinfo is None:
        raise ValueError('Timezone-aware dates required')
    if published > as_of:
        return {'company_id': company.id, 'news_id': news.id, 'score': 0,
                'eligible': False, 'reasons': ['future_publication'], 'missing_data': []}
    if 'not_business' in news.topics:
        return {'company_id': company.id, 'news_id': news.id, 'score': 0,
                'eligible': False, 'reasons': ['not_business'], 'missing_data': []}
    score, reasons = 0, []
    topics = industry_topics(company).intersection(news.topics)
    if topics:
        score += 70
        reasons.append({'feature': 'okved_topic', 'matched': sorted(topics), 'weight': 70})
    if company.registration_region and company.registration_region in news.regions:
        score += 15
        reasons.append({'feature': 'registration_region', 'weight': 15,
                        'limitation': 'Registration does not establish operating geography'})
    countries = set(company.trade_countries or []).intersection(news.countries)
    if countries:
        score += 15
        reasons.append({'feature': 'known_trade_country', 'matched': sorted(countries), 'weight': 15})
    age = (as_of - published).total_seconds() / 86400
    # Soft freshness penalty, never used as evidence of applicability.
    freshness = 1.0 if age <= 7 else 0.8 if age <= 30 else 0.5
    missing = []
    if company.trade_countries is None:
        missing.append('trade_countries')
    if not topics:
        missing.append('confirmed_business_exposure')
    return {'company_id': company.id, 'news_id': news.id,
            'score': round(min(score, 100) * freshness), 'eligible': True,
            'reasons': reasons, 'missing_data': missing}
