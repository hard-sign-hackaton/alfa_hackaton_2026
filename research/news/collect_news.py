"""Small N01/N02 experiment: RSS -> public article HTML -> normalized JSON. No LLM."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).parent
SOURCES = {
    'kommersant': {'name': 'Коммерсантъ', 'feed': 'https://www.kommersant.ru/RSS/news.xml',
                   'selector': '.article_text_wrapper',
                   'sample_terms': ['спрос на сталь', 'доля ozon', 'науфор']},
    'vedomosti': {'name': 'Ведомости', 'feed': 'https://www.vedomosti.ru/rss/news',
                  'selector': '.article__body',
                  'sample_terms': ['цена на природный газ', 'фас с начала', 'непубличных кредитных']},
}

def clean(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def date_iso(value):
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            raise ValueError('RSS date without timezone')
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid publication date: '+str(value)) from exc


def load_feed(raw):
    root = ET.fromstring(raw)
    return root.findall('.//item')


def extract_text(html, selector):
    soup = BeautifulSoup(html, 'html.parser')
    node = soup.select_one(selector)
    if node is None:
        raise ValueError('Article body selector not found: '+selector)
    # Ведомости: контейнер содержит также заголовок, автора и навигацию;
    # берем абзацы. Коммерсантъ: текст может быть размечен div, а не p.
    paragraphs = node.select('p')
    text = '\n\n'.join(clean(p.get_text(' ', strip=True)) for p in paragraphs) if paragraphs else clean(node.get_text(' ', strip=True))
    if len(text) < 200:
        raise ValueError('Insufficient article text')
    return text


TOPIC_RULES = {
    'metallurgy': ['сталь', 'металл'],
    'retail_ecommerce': ['ozon', 'маркетплейс', 'селлер'],
    'financial_markets': ['науфор', 'инвестирован', 'кредитных рейтинг', 'офз'],
    'energy': ['газ в европе', 'топлив', 'нефт'],
    'regulation': ['фас', 'госдума', 'стандарт'],
}


def classify_topics(title):
    return [topic for topic, terms in TOPIC_RULES.items() if any(term in title.lower() for term in terms)] or ['other_business']


def collect(per_source=3, use_snapshot=False, curated=False, offline=False):
    raw_dir = BASE / 'raw'
    raw_dir.mkdir(exist_ok=True)
    records, checks = [], []
    session = requests.Session()
    session.headers['User-Agent'] = 'AlfaHackNewsResearch/0.1'
    for source_id, config in SOURCES.items():
        raw = (BASE / (source_id+'.xml')).read_bytes() if use_snapshot else session.get(config['feed'], timeout=25)
        if not use_snapshot:
            raw.raise_for_status()
            raw = raw.content
        (raw_dir / (source_id+'.xml')).write_bytes(raw)
        accepted = 0
        for item in load_feed(raw):
            title = clean(item.findtext('title'))
            category = clean(item.findtext('category'))
            # Curated mode makes the research sample diverse; default uses broad business rubrics.
            if curated:
                eligible = any(term in title.lower() for term in config['sample_terms'])
            else:
                eligible = any(term in category.lower() for term in ['эконом', 'финанс', 'бизнес', 'индустр', 'инвестиц', 'технолог', 'медиа и телеком'])
            if not eligible:
                continue
            url = item.findtext('link')
            check = {'source': source_id, 'url': url, 'checked_at': datetime.now(timezone.utc).isoformat()}
            try:
                record_id = hashlib.sha256(url.encode()).hexdigest()[:20]
                if offline:
                    html = (raw_dir / (record_id+'.html')).read_text(encoding='utf-8')
                    check.update(mode='offline_snapshot', status=None)
                    fetched_url = url
                else:
                    time.sleep(1)
                    response = session.get(url, timeout=25)
                    check['status'] = response.status_code
                    response.raise_for_status()
                    response.encoding = response.apparent_encoding
                    html = response.text
                    fetched_url = response.url
                text = extract_text(html, config['selector'])
                record_id = hashlib.sha256(url.encode()).hexdigest()[:20]
                (raw_dir / (record_id+'.html')).write_text(html, encoding='utf-8')
                record = {
                    'id': record_id, 'source': config['name'], 'source_id': source_id,
                    'url': url, 'fetched_url': fetched_url, 'title': title,
                    'published_at': date_iso(item.findtext('pubDate')),
                    'collected_at': datetime.now(timezone.utc).isoformat(),
                    'text': text, 'text_kind': 'article_body_extracted',
                    'topics': classify_topics(title), 'topics_method': 'title_keyword_rules_v1',
                    'publisher_categories': [category] if category else [],
                    'ingestion': {'feed_url': config['feed'], 'method': 'rss+html', 'selector': config['selector'],
                                  'raw_html': 'raw/'+record_id+'.html', 'text_sha256': hashlib.sha256(text.encode()).hexdigest()},
                }
                records.append(record)
                check.update(text_chars=len(text), result='ok')
                accepted += 1
            except (requests.RequestException, ValueError) as exc:
                check.update(result='error', error=str(exc))
            checks.append(check)
            if accepted >= per_source:
                break
    for name, data in [('news_examples.json', records), ('article_checks.json', checks)]:
        (BASE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    counts = Counter(r['source_id'] for r in records)
    if any(counts[source_id] < per_source for source_id in SOURCES):
        raise RuntimeError('Not enough articles: '+str(counts)+'; inspect article_checks.json')
    assert len({r['url'] for r in records}) == len(records)
    assert all(r['title'] and r['published_at'] and r['text'] and r['topics'] for r in records)
    print(json.dumps({'articles': len(records), 'by_source': dict(counts), 'text_lengths': [len(r['text']) for r in records]}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--per-source', type=int, default=3)
    parser.add_argument('--snapshot', action='store_true', help='Use RSS captured by probe_sources.py')
    parser.add_argument('--offline', action='store_true', help='Use saved HTML; requires --snapshot')
    parser.add_argument('--curated', action='store_true', help='Reproduce six diverse business examples from the research snapshot')
    args = parser.parse_args()
    if args.per_source < 1:
        parser.error('--per-source must be positive')
    if args.offline and not args.snapshot:
        parser.error('--offline requires --snapshot')
    collect(args.per_source, args.snapshot, args.curated, args.offline)
