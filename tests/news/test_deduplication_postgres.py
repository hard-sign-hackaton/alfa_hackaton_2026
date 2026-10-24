"""Real transactions on an explicit, disposable *_test database only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import os
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.modules.news.deduplication import DEDUPLICATION_WINDOW
from app.modules.news.dto import NewsArticleDTO, ParsedArticle
from app.modules.news.config import Settings
from app.modules.news.identity import article_id
from app.modules.news.models import Article, Embedding, EmbeddingProfile
from app.modules.news.parsers.registry import SOURCES
from app.modules.news.repositories import NewsRepository, NewsEmbeddingRepository
from app.shared.db.session import get_session_factory
from app.modules.news.services.ingestion import NewsIngestionService, collect_parallel

URL = os.getenv('NEWS_TEST_DATABASE_URL')


class DeduplicationFixtures:
    @classmethod
    def setUpClass(cls):
        if not make_url(URL).database.endswith('_test'):
            raise ValueError('Integration tests require a dedicated *_test database')
        cls.sessions = get_session_factory(URL)
        cls.repo = NewsRepository(cls.sessions)
        cls.repo.seed([s.source for s in SOURCES.values()])

    def setUp(self):
        self.token = uuid.uuid4().hex
        self.ids = []
        self.profiles = []
        self.now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        self.body = ('Синтетическая публикация ' + self.token + '. Компания «Альфа» — поставщик. '
                     'Альфа купила компанию Бета 20 октября за 12,5 млн рублей. '
                     'Сделка не предусматривает увеличение долга. Поставка ожидается в декабре.')

    def tearDown(self):
        with self.sessions.begin() as s:
            s.execute(delete(Article).where(Article.id.in_(self.ids)))
            s.execute(delete(EmbeddingProfile).where(EmbeddingProfile.id.in_(self.profiles)))

    def article(self, suffix, **changes):
        source = changes.pop('source_id', 'kommersant')
        url = 'https://example.test/' + self.token + '/' + suffix
        article = NewsArticleDTO(id=article_id(url), url=url, source_id=source, publisher=source,
            title='Synthetic title ' + suffix, text=self.body, published_at=self.now,
            collected_at=self.now, date_provenance='fixture', extraction_method='fixture')
        self.ids.append(article.id)
        return article.model_copy(update=changes)

    def count(self):
        with self.sessions() as s:
            return len(s.scalars(select(Article.id).where(Article.id.in_(self.ids))).all())



@unittest.skipUnless(URL, 'Set NEWS_TEST_DATABASE_URL to a disposable *_test database')
class DeduplicationPostgresTests(DeduplicationFixtures, unittest.TestCase):
    def test_existing_copy_other_source_different_title_is_skipped(self):
        original = self.article('first')
        self.assertEqual(self.repo.save_deduplicated(original).outcome, 'inserted')
        # A new repository instance has no in-memory knowledge of the first save.
        result = NewsRepository(self.sessions).save_deduplicated(self.article('copy', source_id='interfax',
            text=self.body.upper().replace('«', '“').replace('»', '”').replace('—', '–').replace(' ', '\n\n')))
        self.assertEqual(result.outcome, 'duplicate')
        self.assertEqual((result.original_id, result.original_url, result.reason),
                         (original.id, original.url, 'normalized_body_equal'))
        self.assertEqual(self.count(), 1)

    def test_copy_of_legacy_saved_article_is_skipped(self):
        original = self.article('legacy')
        self.repo.save(original)
        self.assertEqual(self.repo.save_deduplicated(self.article('copy')).original_id, original.id)

    def test_parallel_collection_saves_one_copy_and_reports_other_sources(self):
        sources = []
        for source_id, source in SOURCES.items():
            def parse(url, html, ref, source_id=source_id):
                return ParsedArticle(source_id, source_id, url, 'Synthetic ' + source_id,
                    self.body, self.now, self.now, 'fixture', 'fixture')
            sources.append(SimpleNamespace(id=source_id, source=source.source,
                is_article=lambda url: True, parse=parse))
            self.ids.append(article_id('https://example.test/' + self.token + '/' + source_id))

        class Client:
            def __init__(self, source, settings):
                self.count = 0
            def get(self, url):
                self.count += 1
                return url, b'', ''
            def close(self):
                pass

        def discover(source, *args):
            return [{'url': 'https://example.test/' + self.token + '/' + source.id}]
        def offline(*args):
            return collect_parallel(*args, client_factory=Client)
        with patch('app.modules.news.services.ingestion.discover', side_effect=discover), \
             patch('app.modules.news.services.ingestion.collect_parallel', side_effect=offline):
            result = NewsIngestionService(self.repo, sources, Settings()).collect(
                self.now - timedelta(days=1), self.now + timedelta(days=1))
        reports = result['reports']
        self.assertEqual(self.count(), 1)
        self.assertEqual(sum(r['saved'] for r in reports), 1)
        self.assertEqual(sum(r['duplicates'] for r in reports), 2)
        self.assertTrue(all(r['status'] == 'completed' and not r['errors'] for r in reports))
        with self.sessions() as s:
            original_id = s.scalar(select(Article.id).where(Article.id.in_(self.ids)))
        for report in reports:
            for match in report['duplicate_matches']:
                self.assertEqual(match['original_id'], original_id)
        # Reports are persisted through the existing JSONB run mechanism.
        self.repo.record_run(reports[0])

    def test_window_inclusive_in_both_directions(self):
        original = self.article('original')
        self.repo.save_deduplicated(original)
        for delta in (DEDUPLICATION_WINDOW, -DEDUPLICATION_WINDOW):
            with self.subTest(delta=delta):
                result = self.repo.save_deduplicated(self.article(str(delta), published_at=self.now + delta))
                self.assertEqual(result.outcome, 'duplicate')
        for index, delta in enumerate((DEDUPLICATION_WINDOW + timedelta(microseconds=1),
                                       -DEDUPLICATION_WINDOW - timedelta(microseconds=1))):
            self.assertEqual(self.repo.save_deduplicated(self.article('outside'+str(index),
                published_at=self.now + delta)).outcome, 'inserted')
        self.assertEqual(self.count(), 3)

    def test_similar_news_with_different_facts_are_preserved(self):
        self.repo.save_deduplicated(self.article('original'))
        for index, body in enumerate((self.body.replace('12,5', '13,5'),
            self.body.replace('не предусматривает', 'предусматривает'),
            self.body.replace('Бета', 'Гамма'), self.body.replace('20 октября', '21 октября'),
            self.body.replace('купила', 'планирует купить'), self.body + ' Поставка отложена.',
            self.body.replace('Альфа купила компанию Бета', 'Бета купила компанию Альфа'),
            'Иная публикация на ту же тему: компания Альфа обсуждает покупку Беты.')):
            with self.subTest(index=index):
                self.assertEqual(self.repo.save_deduplicated(self.article(str(index),
                    title='Одинаковый заголовок', text=body)).outcome, 'inserted')
        self.assertEqual(self.count(), 9)

    def test_same_url_upsert_and_embedding_invalidation(self):
        article = self.article('same')
        self.assertEqual(self.repo.save_deduplicated(article).outcome, 'inserted')
        vectors = NewsEmbeddingRepository(self.sessions)
        profile = hashlib.sha256(self.token.encode()).hexdigest()
        self.profiles.append(profile)
        vectors.ensure_profile(dict(id=profile, model='test', revision='test', dimensions=384,
                                    normalized=True, preparation='test'))
        pending = next(a for a in vectors.pending(profile, 1000) if a.id == article.id)
        self.assertTrue(vectors.save_embedding(pending, profile, [1.0] + [0.0]*383, 1))
        self.assertEqual(self.repo.save_deduplicated(article).outcome, 'unchanged')
        with self.sessions() as s:
            self.assertIsNotNone(s.scalar(select(Embedding).where(Embedding.article_id == article.id)))
        changed = article.model_copy(update={'text': article.text + ' Новые сведения.'})
        self.assertEqual(self.repo.save_deduplicated(changed).outcome, 'updated')
        with self.sessions() as s:
            self.assertIsNone(s.scalar(select(Embedding).where(Embedding.article_id == article.id)))
        self.assertEqual(self.count(), 1)

    def test_concurrent_copies_use_independent_connections(self):
        barrier = threading.Barrier(2)
        originals = [self.article('race0'), self.article('race1', source_id='interfax')]
        def save(article):
            engine = create_engine(URL)
            try:
                repository = NewsRepository(sessionmaker(engine))
                barrier.wait(timeout=10)
                return repository.save_deduplicated(article)
            finally:
                engine.dispose()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, originals))
        self.assertCountEqual([r.outcome for r in results], ['inserted', 'duplicate'])
        winner = originals[next(i for i, r in enumerate(results) if r.outcome == 'inserted')]
        duplicate = next(r for r in results if r.outcome == 'duplicate')
        self.assertEqual(duplicate.original_id, winner.id)
        self.assertEqual(self.count(), 1)


@unittest.skipUnless(URL, 'Set NEWS_TEST_DATABASE_URL to a disposable *_test database')
class HybridDeduplicationPostgresTests(DeduplicationFixtures, unittest.TestCase):
    def embeddings(self, *, different=False):
        import numpy as np
        from app.modules.news.services.embedding import NewsEmbeddingService
        from app.shared.embeddings.provider import EmbeddingModelInfo

        class Provider:
            info = EmbeddingModelInfo('synthetic-only', self.token, 384, True)
            max_input_tokens = 512
            def tokenize(inner, text):
                return list(map(ord, text))
            def document_window(inner, title, body):
                return title + [0] + body
            def encode_windows(inner, windows):
                vectors = []
                for window in windows:
                    vector = np.zeros(384, dtype=np.float32)
                    is_other = different and 'different' in ''.join(map(chr, window))
                    vector[1 if is_other else 0] = 1
                    vectors.append(vector)
                return np.asarray(vectors)
            def encode_query(inner, query):
                return np.array([1.0] + [0.0]*383, dtype=np.float32)

        class CountingEmbeddings(NewsEmbeddingService):
            def __init__(inner):
                super().__init__(NewsEmbeddingRepository(self.sessions), Provider())
                inner.encoded = []
            def encode_articles(inner, articles):
                inner.encoded.extend(a.id for a in articles)
                return super().encode_articles(articles)

        service = CountingEmbeddings()
        self.profiles.append(service.profile['id'])
        return service

    def pair(self, **kwargs):
        text = self.body + ' Представитель сообщил об условиях соглашения.'
        return (self.article('original', text=text), self.article('copy',
            text=text.replace('сообщил', 'заявил'), **kwargs))

    def test_hybrid_duplicate_caches_original_and_regular_embed_does_no_work(self):
        embeddings = self.embeddings()
        original, copy = self.pair()
        self.repo.save_deduplicated(original, embeddings=embeddings)
        self.assertEqual(embeddings.encoded, [])
        result = self.repo.save_deduplicated(copy, embeddings=embeddings)
        self.assertEqual(result.outcome, 'duplicate')
        self.assertEqual(result.reason, 'hybrid_text_embedding')
        self.assertGreaterEqual(result.text_similarity, .85)
        self.assertGreaterEqual(result.embedding_similarity, .97)
        self.assertCountEqual(embeddings.encoded, [original.id, copy.id])
        third = self.article('third', text=original.text.replace('сообщил', 'отметил'))
        self.assertEqual(self.repo.save_deduplicated(third, embeddings=embeddings).outcome, 'duplicate')
        self.assertEqual(embeddings.encoded.count(original.id), 1)
        before = list(embeddings.encoded)
        self.assertEqual(embeddings.run()['saved'], 0)
        self.assertEqual(embeddings.encoded, before)
        self.assertEqual(self.count(), 1)

    def test_low_cosine_retains_both_and_both_vectors_are_reused_by_embed(self):
        embeddings = self.embeddings(different=True)
        original, copy = self.pair(title='different')
        self.repo.save_deduplicated(original, embeddings=embeddings)
        self.assertEqual(self.repo.save_deduplicated(copy, embeddings=embeddings).outcome, 'inserted')
        self.assertEqual(self.count(), 2)
        self.assertCountEqual(embeddings.encoded, [original.id, copy.id])
        before = list(embeddings.encoded)
        self.assertEqual(embeddings.run()['saved'], 0)
        self.assertEqual(embeddings.encoded, before)
        # Same URL doesn't perform semantic work; changed content invalidates only its own vector.
        self.assertEqual(self.repo.save_deduplicated(copy, embeddings=embeddings).outcome, 'unchanged')
        changed = copy.model_copy(update={'text': copy.text + ' Дополнение.'})
        self.assertEqual(self.repo.save_deduplicated(changed, embeddings=embeddings).outcome, 'updated')
        self.assertEqual(embeddings.run()['saved'], 1)
        self.assertEqual(embeddings.encoded.count(original.id), 1)
        self.assertEqual(embeddings.encoded.count(copy.id), 2)

    def test_compatible_stored_vector_is_not_recomputed(self):
        embeddings = self.embeddings()
        original, copy = self.pair()
        self.repo.save(original)
        self.assertEqual(embeddings.run()['saved'], 1)
        self.assertEqual(self.repo.save_deduplicated(copy, embeddings=embeddings).outcome, 'duplicate')
        self.assertEqual(embeddings.encoded.count(original.id), 1)

    def test_mismatched_or_stale_vector_cannot_determine_deduplication(self):
        embeddings = self.embeddings()
        original, copy = self.pair()
        self.repo.save(original)
        foreign_id = hashlib.sha256((self.token+'foreign').encode()).hexdigest()
        self.profiles.append(foreign_id)
        foreign = dict(embeddings.profile, id=foreign_id, revision='foreign')
        vectors = NewsEmbeddingRepository(self.sessions)
        vectors.ensure_profile(foreign)
        pending = next(a for a in vectors.pending(foreign_id, 1000) if a.id == original.id)
        vectors.save_embedding(pending, foreign_id, [0.0, 1.0]+[0.0]*382, 1)
        self.assertEqual(self.repo.save_deduplicated(copy, embeddings=embeddings).outcome, 'duplicate')
        self.assertEqual(embeddings.encoded.count(original.id), 1)
        # A mismatched content hash must also be ignored, even for the correct profile.
        with self.sessions.begin() as s:
            row = s.scalar(select(Embedding).where(Embedding.article_id == original.id,
                                                  Embedding.profile_id == embeddings.profile['id']))
            row.input_hash = 'stale'
            row.vector = [0.0, 1.0]+[0.0]*382
        self.assertEqual(self.repo.save_deduplicated(copy, embeddings=embeddings).outcome, 'duplicate')
        self.assertEqual(embeddings.encoded.count(original.id), 2)

    def test_fact_difference_and_exact_copy_do_not_load_model(self):
        from unittest.mock import Mock
        embeddings = Mock()
        original, copy = self.pair()
        self.repo.save_deduplicated(original, embeddings=embeddings)
        exact = self.article('exact', text=original.text)
        self.assertEqual(self.repo.save_deduplicated(exact, embeddings=embeddings).outcome, 'duplicate')
        changed = copy.model_copy(update={'text': copy.text.replace('12,5', '13,5')})
        self.assertEqual(self.repo.save_deduplicated(changed, embeddings=embeddings).outcome, 'inserted')
        embeddings.encode_articles.assert_not_called()
        self.assertEqual(embeddings.mock_calls, [])

    def test_model_failure_retains_story_and_regular_embed_can_finish(self):
        embeddings = self.embeddings()
        original, copy = self.pair()
        self.repo.save(original)
        with patch.object(embeddings, 'encode_articles', side_effect=RuntimeError('offline')):
            result = self.repo.save_deduplicated(copy, embeddings=embeddings)
        self.assertEqual(result.outcome, 'inserted')
        self.assertEqual(result.limitation, 'embedding_unavailable')
        self.assertEqual(self.count(), 2)
        self.assertEqual(embeddings.run()['saved'], 2)

    def test_parallel_hybrid_copies_compute_original_only_once(self):
        embeddings = self.embeddings()
        original, copy = self.pair()
        self.repo.save(original)
        third = self.article('third', text=original.text.replace('сообщил', 'отметил'))
        barrier = threading.Barrier(2)
        def save(article):
            engine = create_engine(URL)
            try:
                barrier.wait(timeout=10)
                return NewsRepository(sessionmaker(engine)).save_deduplicated(article, embeddings=embeddings)
            finally:
                engine.dispose()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, [copy, third]))
        self.assertEqual([r.outcome for r in results], ['duplicate', 'duplicate'])
        self.assertEqual(embeddings.encoded.count(original.id), 1)
        self.assertEqual(len(embeddings.encoded), 3)
        self.assertEqual(self.count(), 1)

    def test_cosine_threshold_and_incoming_encoded_once_for_multiple_candidates(self):
        import numpy as np
        embeddings = self.embeddings()
        original, copy = self.pair()
        other = self.article('other', text=original.text.replace('сообщил', 'отметил'),
                             collected_at=self.now + timedelta(seconds=1))
        self.repo.save(original)
        self.repo.save(other)
        calls = []
        def encode(articles):
            outputs = []
            for a in articles:
                calls.append(a.id)
                # First candidate fails; second passes the semantic threshold.
                cosine = .9699 if a.id == original.id else .9701 if a.id == other.id else 1.0
                v = np.zeros(384, dtype=np.float32)
                v[0], v[1] = cosine, (1-cosine*cosine)**.5
                outputs.append((v, 1))
            return outputs
        with patch.object(embeddings, 'encode_articles', side_effect=encode):
            result = self.repo.save_deduplicated(copy, embeddings=embeddings)
        self.assertEqual(result.outcome, 'duplicate')
        self.assertEqual(result.original_id, other.id)
        self.assertGreaterEqual(result.embedding_similarity, .97)
        self.assertEqual(calls.count(copy.id), 1)
        self.assertEqual(len(calls), 3)

    def test_invalid_embedding_falls_back_without_storing_fake_vector(self):
        embeddings = self.embeddings()
        original, copy = self.pair()
        self.repo.save(original)
        with patch.object(embeddings, 'encode_articles', return_value=[([0.0]*384, 1)]):
            result = self.repo.save_deduplicated(copy, embeddings=embeddings)
        self.assertEqual(result.outcome, 'inserted')
        self.assertEqual(result.limitation, 'embedding_unavailable')
        with self.sessions() as s:
            self.assertEqual(list(s.scalars(select(Embedding).where(Embedding.article_id.in_(self.ids)))), [])

    def test_candidate_encoding_failure_does_not_recompute_incoming_on_embed(self):
        embeddings = self.embeddings()
        original, copy = self.pair()
        self.repo.save(original)
        encode = embeddings.encode_articles
        def fail_candidate(articles):
            if articles[0].id == original.id:
                raise RuntimeError('synthetic failure')
            return encode(articles)
        with patch.object(embeddings, 'encode_articles', side_effect=fail_candidate):
            result = self.repo.save_deduplicated(copy, embeddings=embeddings)
        self.assertEqual(result.outcome, 'inserted')
        self.assertEqual(result.limitation, 'embedding_unavailable')
        self.assertEqual(embeddings.run()['saved'], 1)
        self.assertEqual(embeddings.encoded.count(copy.id), 1)
        self.assertEqual(embeddings.encoded.count(original.id), 1)

    def test_collect_embed_export_and_search_share_the_same_vectors(self):
        from app.modules.news.services.export import NewsExportService
        from app.modules.news.services.search import NewsSearchService
        embeddings = self.embeddings()
        original, copy = self.pair()
        records = {original.url: original, copy.url: copy}
        def parse(url, html, ref):
            a = records[url]
            return ParsedArticle(a.source_id, a.publisher, a.url, a.title, a.text,
                                 a.published_at, a.collected_at, 'fixture', 'fixture')
        source = SimpleNamespace(id='kommersant', source=SOURCES['kommersant'].source,
                                 is_article=lambda url: True, parse=parse)
        class Client:
            def __init__(self, source, settings):
                self.count = 0
            def get(self, url):
                self.count += 1
                return url, b'', ''
            def close(self):
                pass
        def offline(*args):
            return collect_parallel(*args, client_factory=Client)
        with patch('app.modules.news.services.ingestion.discover',
                   return_value=[{'url': u} for u in records]), \
             patch('app.modules.news.services.ingestion.collect_parallel', side_effect=offline):
            service = NewsIngestionService(self.repo, [source], Settings(), embeddings=embeddings)
            result = service.collect(self.now-timedelta(days=1), self.now+timedelta(days=1))
        report = result['reports'][0]
        self.assertEqual((report['saved'], report['duplicates']), (1, 1))
        match = report['duplicate_matches'][0]
        self.assertEqual(match['reason'], 'hybrid_text_embedding')
        self.assertGreaterEqual(match['text_similarity'], .85)
        self.assertGreaterEqual(match['embedding_similarity'], .97)
        self.assertEqual(embeddings.run()['saved'], 0)
        self.assertEqual(len(embeddings.encoded), 2)
        exported = [a for a in NewsExportService(self.repo).export() if a['id'] in self.ids]
        self.assertEqual([a['id'] for a in exported], [original.id])
        hits = NewsSearchService(NewsEmbeddingRepository(self.sessions), embeddings).search('Соглашение',
            as_of=self.now + timedelta(days=1))
        self.assertIn(original.id, [h['id'] for h in hits])
        self.assertNotIn(copy.id, [h['id'] for h in hits])
