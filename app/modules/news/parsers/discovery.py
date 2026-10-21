from defusedxml import ElementTree as ET
import requests
from ..identity import canonical_url
from .base import publication_date

def local(tag):
    return tag.rsplit('}', 1)[-1]


def child_text(node, name):
    return next(((c.text or '').strip() for c in node if local(c.tag) == name), '')


def xml_entries(raw):
    root = ET.fromstring(raw)
    kind = local(root.tag)
    if kind == 'sitemapindex':
        return 'index', [dict(url=child_text(n, 'loc')) for n in root if local(n.tag) == 'sitemap']
    if kind == 'urlset':
        entries = []
        for n in root:
            if local(n.tag) != 'url':
                continue
            published = next(((v.text or '').strip() for v in n.iter() if local(v.tag) == 'publication_date'), None)
            entries.append(dict(url=child_text(n, 'loc'), sitemap_publication=published))
        return 'urls', entries
    if kind in ('rss', 'RDF'):
        return 'rss', [dict(url=child_text(n, 'link'), title=child_text(n, 'title'),
                            published_at=child_text(n, 'pubDate'),
                            categories=[(c.text or '').strip() for c in n if local(c.tag) == 'category'])
                       for n in root.iter() if local(n.tag) == 'item']
    raise ValueError('unsupported_xml_root:' + kind)


def discover(source, client, start, end, settings, report):
    seen = set()
    for endpoint in (source.rss, source.sitemap):
        queue, visited = [endpoint], set()
        while queue:
            if len(visited) >= settings.max_sitemaps:
                report['truncated'] = True
                report['errors'].append(dict(url=endpoint, error='sitemap_budget_exhausted'))
                break
            url = queue.pop(0)
            if url in visited or not source.allowed(url):
                continue
            visited.add(url)
            try:
                _, raw, _ = client.get(url)
                kind, entries = xml_entries(raw)
                if kind == 'index':
                    # No lastmod-based pruning or assumed date ordering.
                    queue.extend(e['url'] for e in entries if e['url'] not in visited and source.allowed(e['url']))
                    continue
                for entry in entries:
                    url = entry['url']
                    if not source.allowed(url) or not source.is_article(url):
                        continue
                    # Genuine publication dates may prune requests; lastmod never can.
                    known = publication_date(entry.get('published_at') or entry.get('sitemap_publication'))
                    if known and not start <= known < end:
                        report['discovery_outside_period'] += 1
                        continue
                    url = canonical_url(url)
                    entry['url'] = url
                    if url not in seen:
                        seen.add(url)
                        yield entry
            except (requests.RequestException, ValueError, RuntimeError, ET.ParseError) as exc:
                report['errors'].append(dict(url=url, error=str(exc)))
                if isinstance(exc, RuntimeError):
                    report['truncated'] = True
                    break
