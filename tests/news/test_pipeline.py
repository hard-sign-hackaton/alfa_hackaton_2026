from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import threading
import unittest
from unittest.mock import patch
import requests
import numpy as np
from app.modules.news.parsers.discovery import xml_entries
from app.modules.news.parsers.http import HttpClient
from app.modules.news.services.ingestion import collect_parallel, collect_source
from app.modules.news.config import period, parse_date, Settings
from app.modules.news.identity import canonical_url, article_id, input_hash
from app.modules.news.dto import NewsArticleDTO as IngestedNews
from app.modules.news.parsers.registry import SOURCES
from app.modules.news.parsers.base import publication_date
from app.modules.news.normalization import normalize_article
from app.shared.embeddings.e5 import E5Provider
from app.shared.embeddings.provider import normalize
from app.modules.news.services.embedding import NewsEmbeddingService


def parsed(source, url, html, reference=None):
    return normalize_article(source.parse(url, html, reference))

ROOT = Path(__file__).resolve().parents[2]
START = parse_date('2026-10-01T00:00:00Z')
END = parse_date('2026-10-22T00:00:00Z')
TEXT = 'A sufficiently long publication body with facts attributed to a source. ' * 6


def html(source, date='2026-10-20T13:00:00Z'):
    selector = {'kommersant': 'class="article_text_wrapper"', 'vedomosti': 'class="article__body"', 'interfax': 'itemprop="articleBody"'}[source]
    return f'<html><h1>Publication title</h1><meta property="article:published_time" content="{date}"><div {selector}><p>{TEXT}</p></div></html>'


class ParserTests(unittest.TestCase):
    def test_url_identity(self):
        url = 'http://www.kommersant.ru/doc/123?utm_source=test#section'
        self.assertEqual(canonical_url(url), 'https://www.kommersant.ru/doc/123')
        self.assertEqual(article_id(url), article_id(canonical_url(url)))
        self.assertNotEqual(input_hash('x', 'y'), input_hash('z', 'y'))

    def test_domain_and_paths(self):
        for source in SOURCES.values():
            self.assertFalse(source.allowed('https://' + source.host + '.evil.org/doc/1'))
            self.assertFalse(source.allowed('https://www.' + source.host + ':8443/doc/1'))
            self.assertFalse(source.is_article('https://www.' + source.host + '/authors/'))

    def test_dates(self):
        self.assertEqual(parse_date('2026-10-20T16:00:00+03:00'), parse_date('2026-10-20T13:00:00Z'))
        self.assertIsNone(publication_date('2026-10-20'))
        self.assertIsNone(publication_date('garbage'))
        with self.assertRaises(ValueError):
            period('2026-10-22T00:00:00Z', '2026-10-20T00:00:00Z')
        with self.assertRaises(ValueError):
            parse_date('2026-10-20')

    def test_each_adapter_and_ai_contract(self):
        from jsonschema import Draft202012Validator, FormatChecker
        schema = json.loads((ROOT / 'research/contracts/t01/ai-news-event.schema.json').read_text(encoding='utf-8'))
        for source in SOURCES.values():
            with self.subTest(source=source.id):
                article = parsed(source,'https://www.' + source.host + '/doc/123', html(source.id))
                self.assertEqual(article.text, TEXT.strip())
                self.assertEqual(article.published_at, parse_date('2026-10-20T13:00:00Z'))
                Draft202012Validator(schema, format_checker=FormatChecker()).validate(article.ai_event())
                self.assertEqual(article.ai_event()['topics'], [])

    def test_ingestion_schema_matches_code(self):
        saved = json.loads((ROOT / 'research/contracts/news-ingestion.schema.json').read_text(encoding='utf-8'))
        saved.pop('$schema')
        self.assertEqual(saved, IngestedNews.model_json_schema())

    def test_real_saved_fixtures(self):
        for sid, file, url in [
            ('kommersant', 'kom_article.html', 'https://www.kommersant.ru/doc/9043090'),
            ('vedomosti', 'ved_article.html', 'https://www.vedomosti.ru/business/news/2026/10/20/1238594-tsena-na-gaz'),
            ('interfax', 'inter_article.html', 'https://www.interfax.ru/business/1123769')]:
            article = parsed(SOURCES[sid],url, (ROOT / 'research/news' / file).read_text(encoding='utf-8'))
            self.assertGreater(len(article.text), 500)
            self.assertEqual(article.published_at.day, 20)

    def test_missing_body_and_paywall(self):
        source = SOURCES['kommersant']
        with self.assertRaisesRegex(ValueError, 'body'):
            parsed(source,'https://www.kommersant.ru/doc/1', '<h1>Title</h1>')
        with self.assertRaisesRegex(ValueError, 'paywall'):
            parsed(source,'https://www.kommersant.ru/doc/1', html(source.id) + '<div class="paywall">Subscribe</div>')

    def test_lastmod_is_not_publication(self):
        source = SOURCES['kommersant']
        modified_only = html(source.id).replace('article:published_time', 'article:modified_time')
        with self.assertRaisesRegex(ValueError, 'unknown_publication'):
            parsed(source,'https://www.kommersant.ru/doc/1', modified_only, {'lastmod': '2026-10-20T00:00:00Z'})

    def test_nested_jsonld_published_not_modified(self):
        page = html('kommersant').replace('article:published_time', 'unused')
        page += '<script type="application/ld+json">{"@graph":[{"@type":"NewsArticle","datePublished":"2026-10-20T00:00:00Z","dateModified":"2026-10-21T00:00:00Z"}]}</script>'
        self.assertEqual(parsed(SOURCES['kommersant'],'https://www.kommersant.ru/doc/1', page).published_at.day, 20)

    def test_xml_namespaces_and_rss(self):
        kind, entries = xml_entries(b'<sitemapindex xmlns="urn:test"><sitemap><loc>https://a/map.xml</loc></sitemap></sitemapindex>')
        self.assertEqual(kind, 'index')
        self.assertEqual(entries[0]['url'], 'https://a/map.xml')
        kind, entries = xml_entries(b'<rss><channel><item><link>https://a/1</link><category>Business</category><pubDate>Tue, 20 Oct 2026 13:00:00 GMT</pubDate></item></channel></rss>')
        self.assertEqual(entries[0]['categories'], ['Business'])
        self.assertEqual(publication_date(entries[0]['published_at']).hour, 13)


class FakeClient:
    barrier = None

    def __init__(self, source, settings):
        self.source, self.count = source, 0

    def get(self, url):
        self.count += 1
        if self.count == 1 and self.barrier:
            self.barrier.wait(timeout=5)
        if url == self.source.rss:
            return url, b'<rss><channel/></rss>', ''
        if url == self.source.sitemap:
            path = '/doc/123' if self.source.id == 'kommersant' else '/business/news/2026/10/20/123-test' if self.source.id == 'vedomosti' else '/business/123'
            link = 'https://www.' + self.source.host + path
            raw = f'<urlset xmlns="urn:test"><url><loc>{link}</loc></url><url><loc>{link}</loc></url></urlset>'.encode()
            return url, raw, ''
        return url, b'', html(self.source.id)

    def close(self):
        pass


class CollectionTests(unittest.TestCase):
    def test_parallel_workers_and_duplicate_urls(self):
        class Parallel(FakeClient):
            barrier = threading.Barrier(3)
        saved = []
        def save(article):
            saved.append(article)
            return 'inserted'
        reports = collect_parallel(list(SOURCES.values()), START, END, 50, Settings(), save, Parallel)
        self.assertEqual(len(saved), 3)
        self.assertTrue(all(r['saved'] == 1 and r['discovered'] == 1 for r in reports))

    def test_worker_failure_isolated(self):
        class Broken(FakeClient):
            def get(self, url):
                if self.source.id == 'interfax':
                    raise RuntimeError('request_budget_exhausted')
                return super().get(url)
        reports = collect_parallel(list(SOURCES.values()), START, END, 50, Settings(), lambda a: 'inserted', Broken)
        self.assertEqual([r['saved'] for r in reports], [1, 1, 0])
        self.assertEqual(reports[-1]['status'], 'failed')

    def test_exclusive_upper_bound(self):
        report = collect_source(SOURCES['kommersant'], START, parse_date('2026-10-20T13:00:00Z'), 50, Settings(), lambda a: 'inserted', FakeClient)
        self.assertEqual(report['saved'], 0)
        self.assertEqual(report['outside_period'], 1)

    def test_unsorted_references_do_not_stop(self):
        class Unsorted(FakeClient):
            def get(self, url):
                if url == self.source.sitemap:
                    raw = '<urlset>' + ''.join(f'<url><loc>https://www.kommersant.ru/doc/{i}</loc><lastmod>2000-01-01</lastmod></url>' for i in range(1, 8)) + '</urlset>'
                    return url, raw.encode(), ''
                if '/doc/' in url:
                    date = '2026-10-20T00:00:00Z' if url.endswith('/7') else '2000-01-01T00:00:00Z'
                    return url, b'', html(self.source.id, date)
                return super().get(url)
        report = collect_source(SOURCES['kommersant'], START, END, 50, Settings(), lambda a: 'inserted', Unsorted)
        self.assertEqual(report['attempted'], 7)
        self.assertEqual(report['saved'], 1)


class EmbeddingTests(unittest.TestCase):
    def test_normalization_validation(self):
        vector = normalize(np.arange(384))
        self.assertEqual(vector.dtype, np.float32)
        self.assertAlmostEqual(float(np.linalg.norm(vector)), 1, places=6)
        for invalid in [np.zeros(384), np.ones(5), np.full(384, np.nan)]:
            with self.assertRaises(ValueError):
                normalize(invalid)

    def test_token_windows_preserve_tail(self):
        # Tokenizer stand-in checks exact budgets/overlap without downloading a model.
        class Tokenizer:
            cls_token_id = 0
            sep_token_id = 0
            def encode(self, text, add_special_tokens=False, **kwargs):
                return list(range(int(text))) if text.isdigit() else [1, 2]
            def build_inputs_with_special_tokens(self, ids):
                return [0] + ids + [0]
        provider = E5Provider.__new__(E5Provider)
        provider.tokenizer = Tokenizer()
        chunks = NewsEmbeddingService(None, provider).chunks('100', '1000')
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(c) <= 512 for c in chunks))
        self.assertEqual(chunks[-1][-2], 999)

    def test_provider_failure_does_not_save_fake_vectors(self):
        class Repo:
            def ensure_profile(self, p): pass
            def pending(self, p, limit): return [object()]
            def save_embedding(self, *args): self.fail = True
        class Provider:
            profile = {'id': 'test'}
            def encode_articles(self, articles): raise RuntimeError('model unavailable')
        repo = Repo()
        class FailingService(NewsEmbeddingService):
            @property
            def profile(self): return {'id': 'test'}
            def encode_articles(self, articles): raise RuntimeError('model unavailable')
        with self.assertRaises(RuntimeError):
            FailingService(repo, None).run()
        self.assertFalse(hasattr(repo, 'fail'))


class HttpTests(unittest.TestCase):
    @staticmethod
    def response(status=200, location=None):
        response = requests.Response()
        response.status_code = status
        response._content = b'<html>Body</html>'
        response._content_consumed = True
        response.encoding = 'utf-8'
        if location:
            response.headers['Location'] = location
        return response

    def test_off_domain_redirect_never_requested(self):
        client = HttpClient(SOURCES['kommersant'], Settings())
        with patch.object(client.session, 'get', return_value=self.response(302, 'https://evil.example/article')) as get, patch('app.modules.news.parsers.http.time.sleep'):
            with self.assertRaisesRegex(ValueError, 'off_domain'):
                client.get('https://www.kommersant.ru/doc/1')
            self.assertEqual(get.call_count, 1)
        client.close()

    def test_temporary_status_retried(self):
        client = HttpClient(SOURCES['kommersant'], Settings())
        with patch.object(client.session, 'get', side_effect=[self.response(503), self.response()]) as get, patch('app.modules.news.parsers.http.time.sleep'):
            client.get('https://www.kommersant.ru/doc/1')
            self.assertEqual(get.call_count, 2)
        client.close()

    def test_permanent_status_not_retried(self):
        client = HttpClient(SOURCES['kommersant'], Settings())
        with patch.object(client.session, 'get', return_value=self.response(404)) as get, patch('app.modules.news.parsers.http.time.sleep'):
            with self.assertRaises(requests.HTTPError):
                client.get('https://www.kommersant.ru/doc/1')
            self.assertEqual(get.call_count, 1)
        client.close()

    def test_request_budget_and_rate_delay(self):
        client = HttpClient(SOURCES['kommersant'], Settings(max_requests=1))
        with patch.object(client.session, 'get', return_value=self.response()), patch('app.modules.news.parsers.http.time.sleep') as sleep:
            client.get('https://www.kommersant.ru/doc/1')
            with self.assertRaisesRegex(RuntimeError, 'budget'):
                client.get('https://www.kommersant.ru/doc/2')
            self.assertEqual(client.count, 1)
            self.assertTrue(sleep.called)
        client.close()


if __name__ == '__main__':
    unittest.main()
