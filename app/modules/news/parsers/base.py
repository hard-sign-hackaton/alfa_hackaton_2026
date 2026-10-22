"""HTML extraction shared by three adapters; no database or validated DTO dependency."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from ..dto import ParsedArticle, SourceDTO

def clean(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def publication_date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def json_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_nodes(child)



class SourceParser:
    def __init__(self, source: SourceDTO, selectors: tuple[str, ...]):
        self.source = source
        self.selectors = selectors

    @property
    def id(self): return self.source.id
    @property
    def name(self): return self.source.name
    @property
    def host(self): return self.source.host
    @property
    def sitemap(self): return self.source.sitemap
    @property
    def rss(self): return self.source.rss

    def allowed(self, url):
        try:
            p = urlsplit(url)
            return p.scheme in ('http', 'https') and p.hostname in (self.host, 'www.' + self.host) and p.port in (None, 80, 443) and not p.username and not p.password
        except ValueError:
            return False

    def is_article(self, url):
        raise NotImplementedError

    def parse(self, url, html, reference=None):
        reference = reference or {}
        soup = BeautifulSoup(html, 'html.parser')
        article_nodes = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                for node in json_nodes(json.loads(script.get_text())):
                    types = node.get('@type', [])
                    types = [types] if isinstance(types, str) else types
                    if any(t in ('NewsArticle', 'Article', 'ReportageNewsArticle') for t in types):
                        article_nodes.append(node)
            except (ValueError, TypeError):
                continue
        if any(n.get('isAccessibleForFree') in (False, 'False', 'false') for n in article_nodes) or soup.select_one('.paywall, .article__paywall, [data-testid="paywall"]'):
            raise ValueError('paywall_detected')
        title_node = soup.select_one('h1')
        title_meta = soup.select_one('meta[property="og:title"]')
        title = clean(title_node.get_text(' ', strip=True) if title_node else title_meta.get('content', '') if title_meta else reference.get('title', ''))
        text, method = '', ''
        for selector in self.selectors:
            body = soup.select_one(selector)
            if body is None:
                continue
            for unwanted in body.select('script, style, nav, aside, .share, .related, .article__related'):
                unwanted.decompose()
            paragraphs = body.select('p')
            text = '\n\n'.join(clean(p.get_text(' ', strip=True)) for p in paragraphs) if paragraphs else clean(body.get_text(' ', strip=True))
            if text:
                method = 'css:' + selector
                break
        if not text:
            for node in article_nodes:
                if isinstance(node.get('articleBody'), str):
                    text = clean(BeautifulSoup(node['articleBody'], 'html.parser').get_text(' ', strip=True))
                    method = 'jsonld:articleBody'
                    break
        dates = []
        for node in soup.select('meta[property="article:published_time"], meta[itemprop="datePublished"], meta[name="datePublished"], meta[name="pubdate"]'):
            dates.append((node.get('content'), 'html:' + (node.get('property') or node.get('itemprop') or node.get('name'))))
        dates.extend((n.get('datePublished'), 'jsonld:datePublished') for n in article_nodes)
        dates.append((reference.get('published_at'), 'rss:pubDate'))
        date, provenance = None, None
        for value, origin in dates:
            date = publication_date(value)
            if date:
                provenance = origin
                break
        return ParsedArticle(source_id=self.id, publisher=self.name,
                            url=url, title=title, text=text, published_at=date,
                            collected_at=datetime.now(timezone.utc), date_provenance=provenance,
                            extraction_method=method, publisher_categories=reference.get('categories', []),
                            limitations=['Extracted public body; completeness and source claims are not independently verified.'])
