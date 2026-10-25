import copy
from http.cookiejar import CookieJar
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
from http.server import ThreadingHTTPServer

from app.web.server import Application, make_handler
from app.modules.feedback.repository import analysis_version


class MemoryFeedback:
    def __init__(self):
        self.rows = {}
    def read(self, company_id, news_id, version, reviewer_id):
        return {'vote': self.rows.get((company_id, news_id, version, reviewer_id))}
    def save(self, state, reviewer_id, vote, *, demo_id=None):
        key = (state['company_id'], state['news_id'], analysis_version(state), reviewer_id)
        if vote is None:
            self.rows.pop(key, None)
        else:
            self.rows[key] = vote
        return {'vote': vote}


class FeedbackApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryFeedback()
        self.app = Application(enable_links=False, runtime=self.temp.name, feedback_repository=self.store)
        self.state = next(iter(self.app.analyses.values()))
        self.data = {'company_id': self.state['company_id'], 'news_id': self.state['news_id'], 'analysis_version': analysis_version(self.state)}
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.app, Path(self.temp.name)))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.cookies = CookieJar()
        self.client = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies))

    def tearDown(self):
        self.app.executor.shutdown(wait=True)
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def get(self, client=None):
        from urllib.parse import urlencode
        with (client or self.client).open(self.base + '/api/feedback?' + urlencode(self.data)) as response:
            return json.load(response)

    def post(self, data, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        return self.client.open(Request(self.base + '/api/feedback', json.dumps(data).encode(), headers=headers))

    def test_vote_is_restored_with_cookie_can_change_and_be_removed(self):
        self.assertIsNone(self.get()['vote'])
        self.assertTrue(next(iter(self.cookies)).has_nonstandard_attr('HttpOnly'))
        for vote in (1, 1, -1):
            with self.post({**self.data, 'vote': vote}) as response:
                self.assertEqual(json.load(response)['vote'], vote)
            self.assertEqual(len(self.store.rows), 1)
            self.assertEqual(self.get()['vote'], vote)
        other = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        self.assertIsNone(self.get(other)['vote'])
        with self.post({**self.data, 'vote': None}):
            pass
        self.assertEqual(self.store.rows, {})

    def test_stale_version_bad_vote_and_spoofed_reviewer_are_rejected(self):
        bad = [{**self.data, 'vote': 2}, {**self.data, 'vote': True}, {**self.data, 'vote': 1, 'reviewer_id': 'other'}]
        for value in bad:
            with self.assertRaises(HTTPError) as error:
                self.post(value)
            self.assertEqual(error.exception.code, 400)
        state = copy.deepcopy(self.state)
        state['result']['summary'] += ' Новая версия.'
        self.app.analyses[(state['company_id'], state['news_id'])] = state
        with self.assertRaises(HTTPError) as error:
            self.post({**self.data, 'vote': 1})
        self.assertEqual(error.exception.code, 409)
        self.assertEqual(self.store.rows, {})

    def test_cross_origin_and_unavailable_database_do_not_record_fake_success(self):
        with self.assertRaises(HTTPError) as error:
            self.post({**self.data, 'vote': 1}, 'https://other.test')
        self.assertEqual(error.exception.code, 403)
        self.app.feedback_repository = None
        with self.assertRaises(HTTPError) as error:
            self.post({**self.data, 'vote': 1})
        self.assertEqual(error.exception.code, 503)
        self.assertEqual(self.store.rows, {})

    def test_demo_feedback_scope_is_derived_from_server_state(self):
        clock = [0]
        from app.web.expert_demo import ExpertDemo
        class ImmediateExecutor:
            def submit(self, fn, *args):
                fn(*args)
        def processor(event, company_id, progress, cancelled):
            state = copy.deepcopy(self.state)
            state.update(company_id=company_id, news_id=event['id'], event=event, is_demo=True)
            return {'state': state, 'matches': [{'company_id': company_id}]}
        self.app.expert_demo = ExpertDemo(processor, ImmediateExecutor(), clock=lambda: clock[0], auto_schedule=False)
        session = self.app.expert_demo.start(self.app.companies[self.data['company_id']])
        clock[0] = 7
        news_id = self.app.expert_demo.view(session['id'], self.data['company_id'])['items'][0]['id']
        state = self.app.analysis(self.data['company_id'], news_id, session['id'])['state']
        data = {'company_id': self.data['company_id'], 'news_id': news_id,
                'analysis_version': analysis_version(state), 'demo_id': session['id'], 'vote': 1}
        with self.post(data) as response:
            self.assertTrue(json.load(response)['is_demo'])
        with self.assertRaises(HTTPError) as error:
            self.post({**self.data, 'vote': 1, 'is_demo': True})
        self.assertEqual(error.exception.code, 400)
