"""Focused company queries and lexical/semantic rank fusion, not impact probabilities."""
from difflib import SequenceMatcher
import json
import math
import re

# Query vocabulary describes an activity. It does not assert customer/supplier roles.
DOMAINS = {
    '24': ('Сталь и металлургия, спрос и цены на металл', ['сталь', 'металлургия', 'металлопродукция']),
    '25': ('Металлоизделия и спрос на сталь', ['металлоизделия', 'сталь']),
    '26': ('Электроника и электронные компоненты', ['электроника', 'микросхемы', 'полупроводники']),
    '29': ('Автомобильный рынок, производство и продажи автомобилей', ['автомобили', 'автопром', 'автокредитование', 'автолизинг']),
    '45': ('Автозапчасти, спрос на автомобили, автокредитование и автолизинг', ['автозапчасти', 'автокомпоненты', 'автомобили', 'автокредитование', 'автолизинг']),
    '46': ('Оптовая торговля, товарный спрос и цепочки поставок', ['оптовая торговля', 'оптовые продажи']),
    '46.43': ('Бытовая техника и электроника, продажи и потребительский спрос', ['бытовая техника', 'электротовары', 'электроника']),
    '47': ('Розничная торговля, потребительский спрос и маркетплейсы', ['розничная торговля', 'маркетплейсы', 'потребление']),
    '49': ('Грузовые перевозки, тарифы и стоимость топлива', ['грузоперевозки', 'перевозки', 'топливо']),
    '52': ('Транспортная логистика, порты, грузоперевозки и ставки фрахта', ['перевозки', 'грузоперевозки', 'пароходства', 'порты', 'фрахт']),
    '68': ('Аренда коммерческой недвижимости, нежилые помещения и арендные ставки', ['коммерческая недвижимость', 'арендные ставки', 'нежилые помещения']),
    '41': ('Строительство зданий, спрос и стоимость строительных материалов', ['строительство', 'стройматериалы']),
    '56': ('Общественное питание, рестораны и цены на продукты', ['рестораны', 'общественное питание', 'продукты', 'овощи']),
    '71': ('Инженерное проектирование и архитектура', ['проектирование', 'архитектура']),
    '35': ('Энергетика, производство электроэнергии и тарифы', ['электроэнергия', 'энерготарифы']),
}


def domain(code):
    candidates = [key for key in DOMAINS if code == key or code.startswith(key + '.')]
    return DOMAINS[max(candidates, key=len)] if candidates else None


def lexical_query(terms):
    return ' OR '.join('"' + term.replace('"', '') + '"' for term in terms)


def _tokens(text):
    return set(re.findall(r'[а-яa-z0-9]+', text.lower().replace('ё', 'е')))


def duplicate(left, right):
    title1, title2 = ' '.join(sorted(_tokens(left['title']))), ' '.join(sorted(_tokens(right['title'])))
    if title1 == title2 or SequenceMatcher(None, title1, title2).ratio() >= .92:
        return True
    a, b = _tokens(left.get('text', '')), _tokens(right.get('text', ''))
    return len(a & b) >= 15 and len(a & b) / max(len(a | b), 1) >= .88


def military_logistics(title):
    value = title.lower()
    return bool(re.search(r'логистическ\w* центр', value) and re.search(r'удар|военн|минобороны|всу', value))


def merge_hits(lexical, semantic, limit, *, excluded=()):
    rows, scores, channels = {}, {}, {}
    for name, values, weight in [('lexical', lexical, 2.0), ('semantic', semantic, 1.0)]:
        seen = set()
        for rank, row in enumerate(values, 1):
            if row['id'] in seen:
                continue
            seen.add(row['id'])
            rows.setdefault(row['id'], row)
            scores[row['id']] = scores.get(row['id'], 0) + weight / (30 + rank)
            channels.setdefault(row['id'], []).append(name)
    selected = []
    for news_id in sorted(rows, key=lambda key: (-scores[key], key)):
        row = rows[news_id]
        if any(duplicate(row, prior) for prior in list(excluded) + selected):
            continue
        selected.append({**row, 'retrieval_score': round(scores[news_id], 8), 'retrieval_channels': channels[news_id]})
        if len(selected) >= limit:
            break
    return selected


def company_search_plan(company, metrics=()):
    plan = []
    for code in company.okved_codes:
        definition = domain(code)
        if definition:
            plan.append({'kind': 'industry', 'query': definition[0], 'lexical_query': lexical_query(definition[1]), 'okved': code})
    finance = any(any(token in service.lower() for token in ('кредит', 'лизинг', 'депозит', 'credit', 'loan', 'leasing', 'deposit')) for service in company.banking_services)
    if finance:
        plan.append({'kind': 'financing', 'query': 'Решения и прогнозы ЦБ по ключевой ставке, стоимость кредитования',
                     'lexical_query': '"ключевая ставка" OR "ставка ЦБ"'})
    for source in metrics:
        if source.kind != 'metric' or source.company_id != company.id or not source.source_id.endswith(':top_okved'):
            continue
        try:
            payload = json.loads(source.text.partition('\n')[2])
        except (ValueError, TypeError):
            continue
        count = 0
        for item in payload.get('top_okved', []):
            code, share = str(item.get('okved_class', '')), item.get('share_pct', 0)
            if not isinstance(share, (float, int)) or not math.isfinite(share) or not 10 <= share <= 100 or domain(code) is None:
                continue
            if any(p.get('okved', '').split('.')[0] == code for p in plan):
                continue
            definition = domain(code)
            plan.append({'kind': 'counterparty', 'query': definition[0], 'lexical_query': lexical_query(definition[1]),
                         'okved': code, 'turnover_share_pct': share, 'source_id': source.source_id,
                         'limitation': 'Известна только отрасль контрагента и доля в обороте; роль и текущая экспозиция не установлены.'})
            count += 1
            if count == 2:
                break
    return plan[:6]


def match_company(reader, company, *, as_of, metrics=(), classifications=None, limit=10):
    if not 1 <= limit <= 100:
        raise ValueError('Candidate limit must be between 1 and 100')
    from retrieval import source_registry, timestamp
    from contracts import NewsEvent
    from ranking import industry_topics
    metrics = list(metrics)
    sentinel = NewsEvent(id='__matching__', title='', text='', url='', published_at=timestamp(as_of).isoformat(), topics=[])
    source_registry(metrics, company, sentinel, as_of=as_of)
    candidates = {}
    plan = company_search_plan(company, metrics)
    for query in plan:
        hits = reader.search_hits(query['query'], lexical_query=query['lexical_query'], as_of=as_of, limit=20)
        for rank, hit in enumerate(hits, 1):
            # Semantics can order lexical candidates but cannot establish an exposure on its own.
            if 'lexical' not in hit.get('retrieval_channels', []):
                continue
            if military_logistics(hit['title']):
                continue
            classification = (classifications or {}).get(hit['id'])
            if classification is not None and not classification['business_relevant']:
                continue
            if query['kind'] == 'industry' and not hit.get('title_match'):
                if classification is None or not industry_topics(company).intersection(classification['topics']):
                    continue
            if query['kind'] == 'counterparty' and not hit.get('title_match'):
                continue
            if query['kind'] == 'financing' and not re.search(r'ключев\w* ставк|ставк\w* цб', hit['title'].lower()):
                continue
            row = candidates.setdefault(hit['id'], {**hit, 'match_reasons': [], 'candidate_score': 0,
                'business_checked': classification is not None, 'requires_impact_analysis': True})
            weight = {'industry': 70, 'financing': 60, 'counterparty': 35}[query['kind']]
            row['candidate_score'] = max(row['candidate_score'], round(weight + 10 / rank, 2))
            row['match_reasons'].append(query)
    selected = []
    for row in sorted(candidates.values(), key=lambda value: (-value['candidate_score'], -value['retrieval_score'], value['id'])):
        if not any(duplicate(row, prior) for prior in selected):
            selected.append(row)
        if len(selected) >= limit:
            break
    return {'company_id': company.id, 'search_plan': plan, 'candidates': selected,
            'limitation': 'Баллы задают порядок кандидатов, а не вероятность, важность или доказанную силу влияния.'}
