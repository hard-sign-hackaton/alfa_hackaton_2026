from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import tempfile
import unittest
from threading import Event
from unittest.mock import patch

from app.web.server import Application, ApiError
from app.web.expert_demo import ExpertDemo


class ManualExecutor:
    def __init__(self):
        self.tasks = []
    def submit(self, fn, *args):
        self.tasks.append((fn, args))
    def run(self):
        fn, args = self.tasks.pop(0)
        fn(*args)


class ExpertDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(runtime=self.temp.name, enable_links=False)
        self.company_id = 'U_37452'
        self.company = self.app.companies[self.company_id]
        self.elapsed = 0
        self.queue = ManualExecutor()
        self.calls = []
        self.snapshot = next(iter(self.app.analyses.values()))
        self.demo = ExpertDemo(self.processor, self.queue, clock=lambda: self.elapsed, auto_schedule=False)
        self.app.expert_demo = self.demo

    def tearDown(self):
        self.app.executor.shutdown(wait=True)
        self.temp.cleanup()

    def processor(self, event, company_id, progress, cancelled):
        self.calls.append(event['id'])
        if event.get('is_repeat'):
            return {'duplicate': True, 'duplicate_of': event['id'].rsplit(':', 1)[0] + ':0'}
        row = {'company_id': company_id, 'news_id': event['id'], 'importance': 'low', 'importance_status': 'ready',
               'analysis_status': 'ready', 'topics': ['financial_markets']}
        progress('matched', 'Actual matcher callback', matches=[row])
        state = deepcopy(self.snapshot)
        state.update(company_id=company_id, news_id=event['id'], event=event, is_demo=True)
        row['analysis_result'] = state
        return {'state': state, 'matches': [row]}

    def test_clock_only_delivers_news_and_never_creates_ready_result(self):
        sid = self.demo.start(self.company)['id']
        self.assertEqual(self.demo.view(sid, self.company_id)['items'], [])
        self.elapsed = 600
        pending = self.demo.view(sid, self.company_id)
        self.assertEqual(pending['received'], 4)
        self.assertEqual((pending['ready'], pending['duplicates']), (0, 0))
        self.assertTrue(all(row['phase'] == 'received' for row in pending['timeline']))
        self.assertTrue(all(not row['classification'].get('importance') for row in pending['items']))
        self.assertEqual(self.calls, [])
        self.queue.run()
        self.assertEqual(self.demo.view(sid, self.company_id)['ready'], 1)
        self.queue.run(); self.queue.run(); self.queue.run()
        done = self.demo.view(sid, self.company_id)
        self.assertEqual((done['ready'], done['duplicates'], done['status']), (3, 1, 'done'))
        self.assertEqual(done['analyses'], 3)
        self.assertNotIn('analysis_result', done['items'][0]['link'])
        detail = self.demo.analysis(sid, self.company_id, done['items'][0]['id'])
        self.assertNotIn('analysis_result', detail['matches'][0])
        self.assertEqual(done['items'][-1]['classification']['importance'], 'low')
        self.assertEqual(len(self.calls), 4)

    def test_real_progress_is_visible_before_worker_completes(self):
        started, finish = Event(), Event()
        def processor(event, company_id, progress, cancelled):
            progress('embedding', 'Real embedding has started')
            started.set()
            self.assertTrue(finish.wait(3))
            return self.processor(event, company_id, progress, cancelled)
        with ThreadPoolExecutor(max_workers=1) as executor:
            demo = ExpertDemo(processor, executor, clock=lambda: self.elapsed, auto_schedule=False)
            sid = demo.start(self.company)['id']
            self.elapsed = 2
            demo.view(sid, self.company_id)
            self.assertTrue(started.wait(2))
            pending = demo.view(sid, self.company_id)
            self.assertEqual(pending['timeline'][0]['phase'], 'embedding')
            self.assertEqual(pending['ready'], 0)
            finish.set()

    def test_failure_and_unmatched_are_explicit_not_fabricated_insights(self):
        for result, expected in [({'state': None, 'matches': []}, 'not_matched'), (RuntimeError('secret'), 'failed')]:
            def processor(*args):
                if isinstance(result, Exception):
                    raise result
                return result
            self.demo.processor = processor
            sid = self.demo.start(self.company)['id']
            self.elapsed += 2
            pending = self.demo.view(sid, self.company_id)
            self.queue.run()
            after = self.demo.view(sid, self.company_id)
            self.assertEqual(after['timeline'][0]['phase'], expected)
            self.assertEqual(after['ready'], 0)
            self.assertNotIn('secret', str(after))
            self.demo.stop(sid, self.company_id)

    def test_stop_cancels_queued_work_and_scope_cannot_cross_company(self):
        sid = self.demo.start(self.company)['id']
        self.elapsed = 2
        news_id = self.demo.view(sid, self.company_id)['items'][0]['id']
        with self.assertRaises(ValueError):
            self.demo.analysis(sid, 'another-company', news_id)
        self.demo.stop(sid, self.company_id)
        self.queue.run()
        self.assertEqual(self.calls, [])
        with self.assertRaises(ValueError):
            self.demo.view(sid, self.company_id)

    def test_unpublished_expired_and_duplicate_active_sessions_are_rejected(self):
        sid = self.demo.start(self.company)['id']
        self.assertEqual(self.demo.start(self.company)['id'], sid)
        with self.assertRaises(ValueError):
            self.demo.analysis(sid, self.company_id, 'demo:' + sid + ':0')
        self.elapsed = self.demo.TTL + 1
        with self.assertRaises(ValueError):
            self.demo.view(sid, self.company_id)

    def test_chat_uses_real_ready_result_and_pending_chat_is_rejected(self):
        sid = self.demo.start(self.company)['id']
        self.elapsed = 2
        news_id = self.demo.view(sid, self.company_id)['items'][0]['id']
        data = {'company_id': self.company_id, 'news_id': news_id, 'demo_id': sid, 'question': 'Какие данные проверить?'}
        with self.assertRaises(ApiError):
            self.app.start_job(data, 'chat')
        self.queue.run()
        called = Event()
        def chat(state, question, history, progress):
            self.assertTrue(state['is_demo'])
            self.assertEqual(state['news_id'], news_id)
            called.set()
            return {'answer': {'company_id': state['company_id'], 'news_id': news_id, 'summary': 'Test'}}
        self.app.chat_runner = chat
        with patch.dict('os.environ', {'LLM_API_KEY': 'test-key'}):
            job = self.app.start_job(data, 'chat')
            self.assertTrue(called.wait(2))
            self.assertTrue(job['is_demo'])
            with self.assertRaises(ApiError):
                self.app.start_job({**data, 'company_id': 'U_128194'}, 'chat')
        self.assertNotIn(news_id, self.app.events)

    def test_one_global_session_survives_profile_switch_and_keeps_results_scoped(self):
        other = self.app.companies['U_128194']
        def processor(event, company_id, progress, cancelled):
            if event.get('is_repeat'):
                return {'duplicate': True, 'duplicate_of': event['id'].rsplit(':', 1)[0] + ':0'}
            if not event.get('target_company_id'):
                return {'states': {}, 'matches': [], 'not_business': True}
            owner = event['target_company_id']
            state = deepcopy(self.snapshot)
            state.update(company_id=owner, news_id=event['id'], event=event, is_demo=True)
            return {'states': {owner: state}, 'matches': [{'company_id': owner, 'analysis_result': state}]}
        self.demo.processor = processor
        sid = self.demo.start([self.company, other], self.company_id)['id']
        self.assertEqual(self.demo.start([self.company, other], other['id'])['id'], sid)
        self.elapsed = 600
        self.demo.view(sid, self.company_id)
        while self.queue.tasks:
            self.queue.run()
        first = self.demo.view(sid, self.company_id)
        second = self.demo.view(sid, other['id'])
        self.assertTrue(first['global'])
        self.assertEqual((first['analyses'], first['processed'], first['duplicates']), (4, 5, 1))
        self.assertEqual(first['id'], second['id'])
        for cid, view in ((self.company_id, first), (other['id'], second)):
            own = [card for card in view['items'] if card['has_analysis']]
            self.assertEqual(len(own), 2)
            for card in own:
                self.assertEqual(self.demo.analysis(sid, cid, card['id'])['state']['company_id'], cid)
        first_news = next(card['id'] for card in first['items'] if card['has_analysis'])
        self.assertIsNone(self.demo.analysis(sid, other['id'], first_news)['state'])

    def test_scenario_requires_real_model_and_ingestion_access(self):
        with patch.dict('os.environ', {'EXPERT_DATABASE_URL': '', 'LLM_API_KEY': ''}):
            with self.assertRaises(ApiError) as error:
                self.app.demo_control({'company_id': self.company_id, 'action': 'start'})
            self.assertEqual(error.exception.status, 503)

    def test_selected_company_is_queued_first_without_excluding_other_members(self):
        other = self.app.companies['U_128194']
        session = self.demo.start([other, self.company], self.company_id)
        self.elapsed = 2
        view = self.demo.view(session['id'], self.company_id)
        self.assertEqual(view['company_count'], 2)
        self.assertEqual(view['items'][0]['target_company_id'], self.company_id)

    def test_restart_restores_results_and_resumes_unfinished_tasks(self):
        demo = ExpertDemo(self.processor, self.queue, clock=lambda: self.elapsed,
                          auto_schedule=False, runtime=self.temp.name)
        sid = demo.start(self.company)['id']
        self.elapsed = 2
        demo.view(sid, self.company_id)
        self.queue.run()
        state = demo.analysis(sid, self.company_id, 'demo:' + sid + ':0')['state']
        restored = ExpertDemo(self.processor, self.queue, clock=lambda: self.elapsed,
                              auto_schedule=False, runtime=self.temp.name)
        self.assertEqual(restored.active_id, sid)
        self.assertEqual(restored.analysis(sid, self.company_id, 'demo:' + sid + ':0')['state'], state)
        self.elapsed = 600
        restored.view(sid, self.company_id)
        self.assertEqual(len(self.queue.tasks), 3)
        restored.stop(sid, self.company_id)
        stopped = ExpertDemo(self.processor, self.queue, runtime=self.temp.name)
        self.assertIsNone(stopped.active_id)

    def test_retry_resubmits_only_failed_tasks(self):
        def failed(*args):
            raise RuntimeError('transport')
        self.demo.processor = failed
        sid = self.demo.start(self.company)['id']
        self.elapsed = 2
        self.demo.view(sid, self.company_id)
        self.queue.run()
        self.assertEqual(self.demo.view(sid, self.company_id)['failed'], 1)
        self.demo.processor = self.processor
        self.demo.retry(sid, self.company_id)
        self.assertEqual(len(self.queue.tasks), 1)
        self.queue.run()
        result = self.demo.view(sid, self.company_id)
        self.assertEqual((result['failed'], result['ready']), (0, 1))
