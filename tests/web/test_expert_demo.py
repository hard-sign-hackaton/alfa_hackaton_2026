import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from threading import Event

from app.web.server import Application, ApiError
from app.web.expert_demo import ExpertDemo


class ExpertDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(runtime=self.temp.name, enable_links=False)
        self.company_id = 'U_37452'
        self.company = self.app.companies[self.company_id]
        self.elapsed = 0
        self.demo = ExpertDemo(clock=lambda: self.elapsed)
        self.app.expert_demo = self.demo

    def tearDown(self):
        self.app.executor.shutdown(wait=True)
        self.temp.cleanup()

    def test_arrivals_matching_analysis_and_duplicate_follow_server_time(self):
        session = self.demo.start(self.company)
        sid = session['id']
        self.assertEqual(session['items'], [])
        self.elapsed = 2
        card = self.demo.view(sid, self.company_id)['items'][0]
        self.assertEqual(card['demo_phase'], 'received')
        self.assertFalse(card['has_analysis'])
        self.elapsed = 4
        self.assertEqual(self.demo.view(sid, self.company_id)['items'][0]['demo_phase'], 'matched')
        self.assertTrue(self.demo.analysis(sid, self.company_id, card['id'])['matched'])
        self.assertFalse(self.demo.analysis(sid, self.company_id, card['id'])['ready'])
        self.elapsed = 7
        result = self.demo.analysis(sid, self.company_id, card['id'])
        self.assertTrue(result['ready'])
        self.assertEqual(result['state']['mode'], 'expert_demo')
        self.elapsed = 26
        finished = self.demo.view(sid, self.company_id)
        self.assertEqual((finished['received'], finished['unique'], finished['ready'], finished['duplicates']), (4, 3, 3, 1))
        self.assertEqual(finished['status'], 'done')
        for item in finished['items']:
            self.assertTrue(item['is_demo'])
            state = self.demo.analysis(sid, self.company_id, item['id'])['state']
            from contracts import Insight, CompanyProfile, NewsEvent, validate_evidence
            validate_evidence(Insight.model_validate(state['result']), CompanyProfile.model_validate(state['company']), NewsEvent.model_validate(state['event']), state['retrieved_sources'])

    def test_scenario_does_not_change_normal_feed_and_cannot_cross_company(self):
        normal = self.app.feed(self.company_id)
        original_count = len(self.app.events), len(self.app.analyses)
        session = self.app.demo_control({'company_id': self.company_id, 'action': 'start'})
        self.elapsed = 7
        feed = self.app.feed(self.company_id, session['id'])
        self.assertEqual(len(feed['items']), len(normal['items']) + 1)
        self.assertEqual((len(self.app.events), len(self.app.analyses)), original_count)
        with self.assertRaises(ApiError):
            self.app.feed('U_128194', session['id'])
        with self.assertRaises(ApiError):
            self.app.start_job({'company_id': self.company_id, 'news_id': feed['items'][0]['id']})
        self.app.demo_control({'company_id': self.company_id, 'demo_id': session['id'], 'action': 'stop'})
        with self.assertRaises(ValueError):
            self.demo.view(session['id'], self.company_id)
        self.assertEqual(len(self.app.feed(self.company_id)['items']), len(normal['items']))

    def test_unpublished_and_expired_demo_are_not_readable(self):
        session = self.demo.start(self.company)
        with self.assertRaises(ValueError):
            self.demo.analysis(session['id'], self.company_id, 'demo:' + session['id'] + ':0')
        self.elapsed = self.demo.TTL + 1
        with self.assertRaises(ValueError):
            self.demo.view(session['id'], self.company_id)

    def test_demo_chat_uses_immutable_ready_state_and_rejects_other_company(self):
        session = self.demo.start(self.company)
        self.elapsed = 7
        news_id = self.demo.view(session['id'], self.company_id)['items'][0]['id']
        called = Event()
        def chat(state, question, history, progress):
            self.assertTrue(state['is_demo'])
            self.assertEqual(state['company_id'], self.company_id)
            called.set()
            return {'answer': {'company_id': state['company_id'], 'news_id': state['news_id'],
                              'summary': 'Тестовый ответ', 'follow_up_answer': 'Тестовый ответ', 'claims': []}}
        self.app.chat_runner = chat
        data = {'company_id': self.company_id, 'news_id': news_id, 'demo_id': session['id'], 'question': 'Какие данные проверить?'}
        with patch.dict('os.environ', {'LLM_API_KEY': 'test-key'}):
            job = self.app.start_job(data, 'chat')
            self.assertTrue(called.wait(2))
            self.assertTrue(job['is_demo'])
            with self.assertRaises(ApiError):
                self.app.start_job({**data, 'company_id': 'U_128194'}, 'chat')
        self.assertNotIn(news_id, self.app.events)
        self.assertNotIn((self.company_id, news_id), self.app.analyses)
