"""Synthetic, offline coverage for collection-time full-body deduplication."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from app.modules.news.config import Settings
from app.modules.news.deduplication import normalized_body, SaveResult
from app.modules.news.dto import ParsedArticle
from app.modules.news.services.ingestion import NewsIngestionService, collect_source

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
BODY = ('Компания «Альфа» — поставщик оборудования. Компания Альфа купила компанию Бета '
        '20 октября за 12,5 млн рублей. Сделка не предусматривает увеличение долга. '
        'Поставка запланирована на декабрь. Участники подтвердили условия соглашения.')


class ComparisonTests(unittest.TestCase):
    def test_typography_case_and_layout(self):
        copy = BODY.replace('«', '“').replace('»', '”').replace('—', '–').upper()
        copy = '\n\n'.join(copy.split(' '))
        self.assertEqual(normalized_body(BODY), normalized_body(copy))
        self.assertEqual(normalized_body('a\u00a0b\tc\r\nd'), 'a b c d')
        self.assertEqual(normalized_body('«тест» ‘цитата’ — итог'),
                         normalized_body('"тест" \'цитата\' - итог'))

    def test_material_changes_are_distinct(self):
        variants = {
            'amount': BODY.replace('12,5', '13,5'),
            'decimal': BODY.replace('12,5', '125'),
            'date': BODY.replace('20 октября', '21 октября'),
            'company': BODY.replace('Бета', 'Гамма'),
            'negation': BODY.replace('не предусматривает', 'предусматривает'),
            'roles': BODY.replace('Альфа купила компанию Бета', 'Бета купила компанию Альфа'),
            'forecast': BODY.replace('купила', 'планирует купить'),
            'addition': BODY + ' Закрытие сделки отложено.',
            'sign': BODY.replace('12,5', '-12,5'),
            'percentage': BODY.replace('12,5 млн', '12,5% млн'),
        }
        for name, variant in variants.items():
            with self.subTest(name=name):
                self.assertNotEqual(normalized_body(BODY), normalized_body(variant))


class FakeSource:
    id = 'synthetic'
    source = object()

    def is_article(self, url):
        return True

    def parse(self, url, html, ref):
        return ParsedArticle(self.id, 'Synthetic', url, 'Test title', BODY,
                             NOW, NOW, 'fixture', 'fixture')


class FakeClient:
    def __init__(self, source, settings):
        self.count = 0

    def get(self, url):
        self.count += 1
        return url, b'', ''

    def close(self):
        pass


class CollectionDeduplicationTests(unittest.TestCase):
    def collect(self, outcomes, limit=None):
        refs = [{'url': f'https://example.test/{i}'} for i in range(len(outcomes))]
        with patch('app.modules.news.services.ingestion.discover', return_value=refs):
            return collect_source(FakeSource(), NOW - timedelta(days=1), NOW + timedelta(days=1),
                                  limit, Settings(), lambda article: outcomes.pop(0), FakeClient)

    def test_all_duplicates_complete_without_errors(self):
        report = self.collect([SaveResult('duplicate', 'original', 'https://original.test/1',
                                          'normalized_body_equal')])
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['saved'], 0)
        self.assertEqual(report['duplicates'], 1)
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['duplicate_matches'], [dict(url='https://example.test/0',
            original_id='original', original_url='https://original.test/1', reason='normalized_body_equal')])

    def test_duplicate_does_not_consume_save_limit(self):
        report = self.collect([SaveResult('duplicate', 'first', 'https://original.test/1',
            'normalized_body_equal'), SaveResult('inserted'), SaveResult('inserted')], limit=1)
        self.assertEqual(report['attempted'], 2)
        self.assertEqual(report['duplicates'], 1)
        self.assertEqual(report['inserted'], 1)
        self.assertEqual(report['saved'], 1)
        self.assertTrue(report['truncated'])

    def test_structured_and_legacy_save_results(self):
        report = self.collect([SaveResult('inserted'), SaveResult('updated'), SaveResult('unchanged'), 'inserted'])
        self.assertEqual((report['inserted'], report['updated'], report['unchanged'], report['saved']), (2, 1, 1, 4))

    def test_service_uses_deduplicated_repository_path(self):
        received = []
        repository = SimpleNamespace(seed=lambda sources: None,
            save_deduplicated=lambda article, **kwargs: received.append(article) or SaveResult('inserted'))
        refs = [{'url': 'https://example.test/1'}]
        # Replace only the HTTP factory; exercise the real parallel collection path.
        from app.modules.news.services.ingestion import collect_parallel
        def offline(*args):
            return collect_parallel(*args, client_factory=FakeClient)
        with patch('app.modules.news.services.ingestion.discover', return_value=refs), \
             patch('app.modules.news.services.ingestion.collect_parallel', side_effect=offline):
            result = NewsIngestionService(repository, [FakeSource()], Settings()).collect(
                NOW - timedelta(days=1), NOW + timedelta(days=1))
        self.assertEqual(len(received), 1)
        self.assertEqual(result['reports'][0]['saved'], 1)


    def test_embedding_failure_is_recorded_without_losing_article(self):
        report = self.collect([SaveResult('inserted', limitation='embedding_unavailable')])
        self.assertEqual(report['saved'], 1)
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['deduplication_limitations'],
                         [{'url': 'https://example.test/0', 'reason': 'embedding_unavailable'}])


class HybridTextTests(unittest.TestCase):
    def test_small_wording_change_passes_candidate_gate(self):
        from app.modules.news.deduplication import hybrid_text_similarity
        original = BODY + ' Представитель сообщил об условиях соглашения.'
        self.assertIsNotNone(hybrid_text_similarity(original, original.replace('сообщил', 'заявил')))

    def test_fact_guards_even_when_character_similarity_is_high(self):
        from app.modules.news.deduplication import hybrid_text_similarity, character_similarity
        original = BODY + ' Представитель сообщил об условиях соглашения.'
        variants = [original.replace('12,5', '13,5'), original.replace('Бета', 'Гамма'),
            original.replace('не предусматривает', 'предусматривает'), original.replace('20 октября', '21 октября'),
            original.replace('купила', 'планирует купить'), original + ' Сделка отменена.',
            original.replace('рублей.', 'рублей, штат сократится.'),
            original.replace('купила', 'продала'), original.replace('млн', 'млрд'),
            original.replace('Альфа купила компанию Бета', 'Бета купила компанию Альфа')]
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertGreater(character_similarity(normalized_body(original), normalized_body(variant)), .85)
                self.assertIsNone(hybrid_text_similarity(original, variant))

    def test_character_threshold_and_order(self):
        from app.modules.news.deduplication import character_similarity
        self.assertAlmostEqual(character_similarity('a'*100, 'a'*85+'b'*15), .85)
        self.assertLess(character_similarity('a'*100, 'a'*84+'b'*16), .85)
        self.assertLess(character_similarity('alpha beta gamma', 'gamma beta alpha'), 1)

    def test_lazy_model_is_shared_and_not_created_at_construction(self):
        from app.modules.news.services.deduplication import LazyNewsEmbeddings
        from app.shared.embeddings.provider import EmbeddingModelInfo
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import Mock
        provider = SimpleNamespace(info=EmbeddingModelInfo('synthetic', 'fixture', 384, True))
        factory = Mock(return_value=provider)
        lazy = LazyNewsEmbeddings(factory)
        factory.assert_not_called()
        with ThreadPoolExecutor(max_workers=3) as pool:
            profiles = list(pool.map(lambda _: lazy.profile, range(3)))
        factory.assert_called_once()
        self.assertTrue(all(p == profiles[0] for p in profiles))


    def test_failed_lazy_initialization_is_not_repeated(self):
        from app.modules.news.services.deduplication import LazyNewsEmbeddings
        from unittest.mock import Mock
        factory = Mock(side_effect=OSError('offline'))
        lazy = LazyNewsEmbeddings(factory)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                _ = lazy.profile
        factory.assert_called_once()
