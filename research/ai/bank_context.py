"""Bank retrieval policy and an explicit distinction between found and cited context."""
import re

TOPIC_QUERIES = {
    'metallurgy': 'металлургия', 'electronics': 'электроника', 'automotive': 'автомобили',
    'construction': 'строительство', 'retail_ecommerce': 'потребление', 'logistics': 'перевозки',
    'financial_markets': 'ключевая ставка', 'energy': 'энергетика',
    'wholesale_trade': 'торговля', 'real_estate': 'недвижимость',
}


def bank_query(news, preparation):
    title = news.title.lower().replace('ё', 'е')
    # Short queries also work in PostgreSQL full-text mode, which combines words with AND.
    for stems, query in (
        (('нефт',), 'нефть'), (('автокредит',), 'автокредитование'),
        (('ключев', 'ставк'), 'ключевая ставка'),
        (('инфляц',), 'инфляция'), (('овощ', 'фрукт'), 'инфляция'),
        (('порт', 'пароход'), 'перевозки'),
    ):
        if any(stem in title for stem in stems):
            return query
    for topic in preparation.classification.topics:
        if topic in TOPIC_QUERIES:
            return TOPIC_QUERIES[topic]
    return news.title[:200]


def needs_bank_refresh(state):
    return bool(state and state.get('preparation', {}).get('classification', {}).get('business_relevant')
                and not state.get('bank_context_version')
                and not any(s.get('kind') == 'bank' for s in state.get('retrieved_sources', [])))


def _digest_text(text):
    text = ' '.join(text.split())
    text = re.sub(r'^В историческом банковском обзоре\s*\([^)]*\)\s*(?:отмечено|указано),?\s*что\s+', '', text)
    text = re.sub(r'^Банковская аналитика отмечает, что\s+', '', text)
    text = re.split(r';\s*это исторический контекст', text, maxsplit=1)[0]
    if text:
        text = text[0].upper() + text[1:]
    return text


def _short(text, limit=190):
    text = _digest_text(text)
    if len(text) <= limit:
        return text
    # The limit is a target: keep a whole first sentence even when it is longer.
    # Uppercase lookahead avoids treating dates, decimals and "г. указывает" as endings.
    endings = [match.end() for match in re.finditer(r'[.!?](?:[»”"])?(?=\s+[А-ЯЁA-Z«]|$)', text)]
    fitting = [end for end in endings if end <= limit]
    return text[:max(fitting) if fitting else endings[0]] if endings else text


def summarize_bank_context(state):
    """Reuse accepted claims, otherwise extract short, attributed source excerpts."""
    sources = {s['source_id']: s for s in state.get('retrieved_sources', []) if s.get('kind') == 'bank'}
    highlights, impact, seen = [], None, set()
    for claim in (state.get('result') or {}).get('claims', []):
        evidence = [e for e in claim.get('evidence', []) if e['source_id'] in sources
                    and e.get('quote') and e['quote'] in sources[e['source_id']].get('text', '')]
        if not evidence or not claim.get('text'):
            continue
        item = {'text': _short(claim['text']), 'full_text': _digest_text(claim['text']),
                'source_ids': list(dict.fromkeys(e['source_id'] for e in evidence)),
                'evidence': evidence, 'method': 'accepted_claim'}
        if claim.get('kind') == 'fact' and item['text'] not in seen and len(highlights) < 1:
            highlights.append(item)
            seen.add(item['text'])
        elif claim.get('kind') == 'hypothesis' and impact is None:
            premises = {e['source_id'] for e in claim.get('evidence', [])}
            if any(s.startswith(('company:' + state.get('company_id', '') + ':',
                                 'metric:' + state.get('company_id', '') + ':')) for s in premises):
                impact = {**item, 'text': _short(claim['text'], 150)}
    if not highlights:
        # OCR headers are metadata, not a summary. Prefer sentences matching the event;
        # keep original substring evidence even when display whitespace is normalized.
        title = state.get('event', {}).get('title', '')
        stems = {word[:5] for word in re.findall(r'[а-яёa-z]{4,}', title.lower())}
        candidates = []
        for source_id, source in sources.items():
            body = source.get('text', '')
            if body.startswith('Документ:') and '\n\n' in body:
                body = body.split('\n\n', 1)[1]
            for sentence in re.split(r'\n+|(?<=[.!?])\s+(?=[А-ЯЁA-Z«])', body):
                quote = sentence.strip().lstrip('-•* ')
                if len(quote) < 45:
                    continue
                score = sum(stem in quote.lower() for stem in stems)
                candidates.append((score, source_id, quote))
        used_documents = set()
        for _, source_id, quote in sorted(candidates, key=lambda item: -item[0]):
            document = source_id.split('#', 1)[0]
            if document in used_documents:
                continue
            text = _short(quote)
            if text in seen:
                continue
            # A short displayed excerpt is still linked to its exact original sentence.
            highlights.append({'text': text, 'full_text': _digest_text(quote), 'source_ids': [source_id],
                'evidence': [{'source_id': source_id, 'quote': quote}], 'method': 'excerpt'})
            seen.add(text)
            used_documents.add(document)
            if len(highlights) == 1:
                break
    return {'highlights': highlights, 'impact': impact,
            'note': None if impact else 'Прямое влияние на компанию не установлено.'}


def describe_bank_context(state):
    state = state or {}
    found = [s['source_id'] for s in state.get('retrieved_sources', []) if s.get('kind') == 'bank']
    cited = {e['source_id'] for claim in (state.get('result') or {}).get('claims', [])
             for e in claim.get('evidence', [])}
    used = [source_id for source_id in found if source_id in cited]
    trace = [entry for entry in state.get('trace', []) if entry.get('tool') == 'search_bank_analytics']
    if found:
        status = 'used' if used else 'retrieved'
    elif any(entry['status'] == 'unavailable' for entry in trace):
        status = 'unavailable'
    elif any(entry['status'] in ('limited', 'rejected') for entry in trace):
        status = 'incomplete'
    else:
        status = 'not_found' if trace else 'not_searched'
    return {'status': status, 'source_ids': found, 'cited_source_ids': used,
            'retrieved_count': len(found), 'cited_count': len(used), 'summary': summarize_bank_context(state)}
