"""Run persistence cases only on an explicitly named disposable test database."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import unittest
import uuid
from sqlalchemy import delete, update
from sqlalchemy.engine import make_url
from app.shared.db.session import get_session_factory
from app.shared.db.migrations import upgrade_database
from app.modules.news.models import Article
from app.modules.news.repositories import NewsRepository
from app.modules.news.parsers.registry import SOURCES
from app.modules.news.dto import NewsArticleDTO
from app.modules.news.identity import article_id
from app.modules.companies.models import Company, CompanyGroup
from app.modules.companies.repositories import CompanyRepository
from app.modules.companies.normalization import normalize_dataset
from app.modules.companies.dto import NormalizedCompany
from app.modules.companies.identity import text_hash
from app.modules.companies.profiling import build_profile_text
from app.modules.links.repository import LinkRepository

URL = os.environ.get('LINKS_TEST_DATABASE_URL')


@unittest.skipUnless(URL, 'Set LINKS_TEST_DATABASE_URL to a disposable *_test database')
class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not make_url(URL).database.endswith('_test'):
            raise ValueError('Dedicated test database required')
        upgrade_database(URL)
        cls.sessions = get_session_factory(URL)
        cls.news = NewsRepository(cls.sessions)
        cls.news.seed([s.source for s in SOURCES.values()])
        cls.companies = CompanyRepository(cls.sessions)
        cls.links = LinkRepository(URL)
        root = Path(__file__).resolve().parents[2]
        cls.dataset = normalize_dataset(json.loads((root / 'docs/companies/companies_analytics.json').read_text(encoding='utf-8')))

    def setUp(self):
        self.token = uuid.uuid4().hex
        self.company_id, self.group_id = 'link-test-' + self.token, 'group-' + self.token
        group = self.dataset.groups[0].model_copy(update={'group_id': self.group_id, 'companies': []})
        self.companies.save_group(group)
        original = self.dataset.companies[0]
        record = original.record.model_copy(update={'company_id': self.company_id,
            'main': original.record.main.model_copy(update={'group_id': self.group_id})})
        profile = build_profile_text(record)
        self.companies.save_company(NormalizedCompany(record=record, profile_text=profile, content_hash=text_hash(profile)))
        url = 'https://www.kommersant.ru/doc/links-test-' + self.token
        self.article = NewsArticleDTO(id=article_id(url), source_id='kommersant', publisher='Test', url=url,
            title='Explicit test publication', text='Synthetic test content about automotive trading.',
            published_at=datetime.now(timezone.utc) - timedelta(days=1), collected_at=datetime.now(timezone.utc),
            date_provenance='test', extraction_method='test')
        self.news.save(self.article)
        self.pair = self.links.ensure(self.company_id, self.article.id, method='hybrid', topics=['automotive'])

    def tearDown(self):
        with self.sessions.begin() as s:
            s.execute(delete(Article).where(Article.id == self.article.id))
            s.execute(delete(Company).where(Company.id == self.company_id))
            s.execute(delete(CompanyGroup).where(CompanyGroup.id == self.group_id))

    def assessment(self):
        return {'level': 'medium', 'reason': 'Test reason', 'evidence': [{'source_id': 'test', 'quote': 'test'}]}

    def state(self, importance=None):
        result = dict(company_id=self.company_id, news_id=self.article.id, event=self.article.ai_event(),
            as_of=datetime.now(timezone.utc).isoformat(), result={'status': 'supported'})
        if importance:
            result['brief'] = {'classification': {'importance': importance, 'importance_reason': 'Full analysis'},
                              'evidence': {'importance': []}}
        return result

    def test_upsert_is_idempotent_and_directional_reads_share_row(self):
        self.links.assessment(self.pair, self.assessment())
        self.links.ensure(self.company_id, self.article.id, method='hybrid')
        forward = self.links.list(company_id=self.company_id)
        reverse = self.links.list(news_id=self.article.id)
        self.assertEqual(forward, reverse)
        self.assertEqual(len(forward), 1)
        self.assertEqual(forward[0]['importance'], 'medium')

    def test_changed_news_hides_old_link_and_rejects_late_model_result(self):
        self.links.assessment(self.pair, self.assessment())
        self.news.save(self.article.model_copy(update={'text': self.article.text + ' Updated.'}))
        self.assertEqual(self.links.list(company_id=self.company_id), [])
        self.assertFalse(self.links.assessment(self.pair, self.assessment()))
        refreshed = self.links.ensure(self.company_id, self.article.id)
        self.assertEqual(refreshed['importance_status'], 'pending')
        self.assertIsNone(refreshed['importance'])

    def test_changed_company_invalidates_assessment(self):
        with self.sessions.begin() as s:
            s.execute(update(Company).where(Company.id == self.company_id).values(content_hash='f' * 64))
        self.assertFalse(self.links.assessment(self.pair, self.assessment()))
        self.assertEqual(self.links.list(news_id=self.article.id), [])

    def test_changed_payment_details_invalidate_even_when_embedding_hash_is_unchanged(self):
        with self.sessions.begin() as s:
            company = s.get(Company, self.company_id)
            original_hash = company.content_hash
            company.details = {**company.details, 'test_snapshot_change': True}
        self.assertEqual(self.links.list(news_id=self.article.id), [])
        pair = self.links.ensure(self.company_id, self.article.id)
        self.assertEqual(pair['company_hash'], original_hash)
        self.assertEqual(pair['importance_status'], 'pending')

    def test_changed_publication_date_invalidates_without_changing_text(self):
        with self.sessions.begin() as s:
            s.execute(update(Article).where(Article.id == self.article.id).values(published_at=self.article.published_at - timedelta(days=1)))
        self.assertEqual(self.links.list(news_id=self.article.id), [])

    def test_superseded_analysis_cannot_overwrite_current_result(self):
        self.links.claim_analysis(self.pair, 'first')
        self.links.claim_analysis(self.pair, 'second')
        self.assertFalse(self.links.analysis(self.pair, self.state(), run_id='first'))
        self.assertTrue(self.links.analysis(self.pair, self.state('high'), run_id='second'))
        self.assertFalse(self.links.analysis_failed(self.pair, 'second'))
        self.assertFalse(self.links.assessment(self.pair, self.assessment()))
        row = self.links.list(news_id=self.article.id)[0]
        self.assertEqual(row['importance'], 'high')
        self.assertEqual(row['analysis_status'], 'ready')

    def test_analysis_persists_across_repository_instances_and_rejects_foreign_pair(self):
        state = self.state()
        self.assertTrue(self.links.analysis(self.pair, state))
        self.assertEqual(LinkRepository(URL).list(news_id=self.article.id)[0]['analysis_result'], state)
        with self.assertRaises(ValueError):
            self.links.analysis(self.pair, {**state, 'company_id': 'other'})

    def test_unknown_company_cannot_create_link(self):
        with self.assertRaises(ValueError):
            self.links.ensure('unknown', self.article.id)


if __name__ == '__main__':
    unittest.main()

    def test_expert_news_vectors_links_and_analysis_are_persistent_but_isolated(self):
        from app.modules.news.models import NewsSource, Embedding, EmbeddingProfile
        from app.modules.news.repositories import NewsEmbeddingRepository
        from app.modules.news.dto import SourceDTO, EmbeddingInput
        from app.modules.news.identity import input_hash
        source_id = 'expert-demo:' + self.token
        demo_id = 'demo:' + self.token + ':0'
        article = self.article.model_copy(update={'id': demo_id, 'source_id': source_id,
            'url': 'https://expert-demo.invalid/' + self.token, 'title': 'ТЕСТ: Снижение ставки',
            'text': 'Вымышленная тестовая публикация: ключевая ставка снижена на один пункт.'})
        self.news.seed([SourceDTO(source_id, 'Expert scenario', 'expert-demo.invalid', '', '')])
        profile = {'id': 'expert-test-' + self.token, 'model': 'fixture', 'revision': 'fixture',
                   'dimensions': 384, 'normalized': True, 'preparation': 'fixture'}
        vectors = NewsEmbeddingRepository(self.sessions)
        try:
            outcome = self.news.save_deduplicated(article, dedup_source_id=source_id)
            self.assertEqual(outcome.outcome, 'inserted')
            record = EmbeddingInput(demo_id, article.title, article.text, input_hash(article.title, article.text))
            vector = [1.] + [0.] * 383
            vectors.ensure_profile(profile)
            self.assertTrue(vectors.save_embedding(record, profile['id'], vector, 1))
            pair = self.links.ensure(self.company_id, demo_id, method='company_embedding', score=.8)
            self.links.assessment(pair, self.assessment())
            state = {'company_id': self.company_id, 'news_id': demo_id, 'event': article.ai_event(),
                     'is_demo': True, 'as_of': datetime.now(timezone.utc).isoformat(), 'result': {'status': 'supported'}}
            self.assertTrue(self.links.claim_analysis(pair, self.token))
            self.assertTrue(self.links.analysis(pair, state, run_id=self.token))
            stored = self.links.list(news_id=demo_id, include_demo=True)
            self.assertEqual(stored[0]['analysis_result'], state)
            self.assertEqual(stored[0]['importance'], 'medium')
            self.assertEqual(self.links.list(news_id=demo_id), [])
            self.assertNotIn(demo_id, [row.id for row in self.news.list_articles()])
            self.assertNotIn(demo_id, [row['id'] for row in self.news.search_text('ставка')])
            self.assertEqual(vectors.search_pg(vector, profile['id'], 5), [])
            self.assertEqual(self.news.get_article(demo_id).id, demo_id)
            duplicate = article.model_copy(update={'id': demo_id[:-1] + '3', 'url': article.url + '/copy'})
            outcome = self.news.save_deduplicated(duplicate, dedup_source_id=source_id)
            self.assertEqual((outcome.outcome, outcome.original_id), ('duplicate', demo_id))
            # Source imports ignore synthetic stories during deduplication.
            normal = article.model_copy(update={'id': self.article.id, 'source_id': self.article.source_id, 'url': self.article.url})
            self.assertNotEqual(self.news.save_deduplicated(normal).outcome, 'duplicate')
        finally:
            with self.sessions.begin() as session:
                session.execute(delete(Article).where(Article.source_id == source_id))
                session.execute(delete(EmbeddingProfile).where(EmbeddingProfile.id == profile['id']))
                session.execute(delete(NewsSource).where(NewsSource.id == source_id))
