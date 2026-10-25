from copy import deepcopy
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.web.expert_pipeline import ExpertPipeline


class ExpertPipelineTests(unittest.TestCase):
    def setUp(self):
        self.event = {'id': 'demo:' + 'a' * 32 + ':0', 'title': 'ТЕСТ: Снижение ставки',
                      'text': 'Вымышленная новость о снижении ставки.', 'published_at': '2026-10-25T00:00:00+00:00',
                      'url': 'https://expert-demo.invalid/test/0'}
        self.steps = []
        self.links, self.articles, self.vectors, self.embeddings = Mock(), Mock(), Mock(), Mock()
        self.articles.save_deduplicated.return_value = SimpleNamespace(outcome='inserted')
        self.embeddings.profile = {'id': 'real-profile'}
        self.embeddings.encode_articles.return_value = [([1., 0.], 1)]
        self.vectors.save_embedding.return_value = True
        self.links.list.return_value = [{'company_id': 'found', 'importance': 'low'}]
        self.links.claim_analysis.return_value = True
        self.links.analysis.return_value = True
        self.state = {'company_id': 'found', 'news_id': self.event['id'], 'is_demo': True,
                      'result': {'summary': 'MODEL OUTPUT'}, 'telemetry': [{'task': 'analysis'}]}
        self.runner = Mock(return_value=self.state)
        self.service = Mock()
        self.service.classifications = {self.event['id']: {'business_relevant': True}}
        self.service.client.telemetry = [{'task': 'classification'}, {'task': 'importance'}]
        def match(news_id, limit, on_matched, on_classified):
            on_classified(); on_matched()
            return {'candidates': [{'id': 'found'}]}
        self.service.match_news.side_effect = match
        self.pipeline = ExpertPipeline(self.links, self.runner)

    def run_pipeline(self, company_id='found'):
        with patch.dict(os.environ, {'EXPERT_DATABASE_URL': 'test-only', 'EXPERT_MATCH_LIMIT': '5'}), \
             patch('app.modules.news.bootstrap.repositories', return_value=(self.articles, self.vectors)), \
             patch('news_repository.NewsReader.from_env') as reader, \
             patch('app.modules.links.service.LinkService', return_value=self.service):
            reader.return_value._semantic.return_value.embeddings = self.embeddings
            return self.pipeline(deepcopy(self.event), company_id,
                lambda phase, stage, **values: self.steps.append(phase), lambda: False)

    def test_real_services_receive_publication_and_model_output_is_saved_unchanged(self):
        result = self.run_pipeline()
        self.assertIs(result['state'], self.state)
        self.assertEqual(result['state']['result']['summary'], 'MODEL OUTPUT')
        self.embeddings.encode_articles.assert_called_once()
        self.vectors.save_embedding.assert_called_once()
        self.service.match_news.assert_called_once()
        self.runner.assert_called_once()
        self.assertEqual(self.runner.call_args.args[:2], ('found', self.event['id']))
        self.assertIs(self.links.analysis.call_args.args[1], self.state)
        self.assertIn('classifying', self.steps)
        self.assertIn('matching', self.steps)
        self.assertIn('analyzing', self.steps)
        self.service.close.assert_called_once()

    def test_duplicate_result_comes_from_storage_and_does_not_call_models(self):
        self.articles.save_deduplicated.return_value = SimpleNamespace(outcome='duplicate', original_id='canonical')
        result = self.run_pipeline()
        self.assertEqual(result, {'duplicate': True, 'duplicate_of': 'canonical'})
        self.runner.assert_not_called()
        self.embeddings.encode_articles.assert_not_called()
        self.service.match_news.assert_not_called()

    def test_current_company_is_not_added_when_matcher_did_not_select_it(self):
        result = self.run_pipeline('not-selected')
        self.assertIsNone(result['state'])
        self.assertEqual(result['matches'][0]['company_id'], 'found')
        self.assertEqual(self.runner.call_args.args[0], 'found')

    def test_model_error_marks_persistent_pair_failed_and_propagates(self):
        self.runner.side_effect = RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            self.run_pipeline()
        self.links.analysis_failed.assert_called_once()
        self.links.analysis.assert_not_called()
        self.service.close.assert_called_once()

    def test_embedding_failure_does_not_start_matching_or_fabricate_analysis(self):
        self.vectors.save_embedding.return_value = False
        with self.assertRaises(ValueError):
            self.run_pipeline()
        self.runner.assert_not_called()
        self.service.match_news.assert_not_called()

    def test_restart_reuses_actual_committed_result_instead_of_calling_models_again(self):
        self.links.list.return_value = [{'company_id': 'found', 'analysis_result': self.state, 'analysis_status': 'ready'}]
        result = self.run_pipeline()
        self.assertTrue(result['reused_analysis'])
        self.assertIs(result['state'], self.state)
        self.runner.assert_not_called()
        self.service.match_news.assert_not_called()

    def test_failed_review_is_not_replaced_by_an_older_cached_result(self):
        self.links.list.return_value = [{'company_id': 'found', 'analysis_result': self.state, 'analysis_status': 'failed'}]
        self.run_pipeline()
        self.runner.assert_called_once()
