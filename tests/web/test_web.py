import json
import os
from pathlib import Path
import tempfile
from threading import Thread, Event
import unittest
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
from http.server import ThreadingHTTPServer

from app.web.server import Application, ApiError, ROOT, make_handler

urlopen = build_opener(ProxyHandler({})).open


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.release = Event()
        def runner(company_id, news_id, progress):
            progress('test')
            self.release.wait(2)
            return {**self.state, 'company_id': company_id, 'news_id': news_id}
        def chat_runner(state, question, history, progress):
            return {'summary': question, 'claims': [], 'follow_up_answer': 'Ответ по выбранному контексту',
                    'company_id': state['company_id'], 'news_id': state['news_id']}
        self.app = Application(enable_links=False, runtime=self.temp.name, runner=runner, chat_runner=chat_runner)
        self.state = next(iter(self.app.analyses.values()))
        self.company_id, self.news_id = self.state['company_id'], self.state['news_id']
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.app, Path(self.temp.name)))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.release.set()
        self.app.executor.shutdown(wait=True)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def post(self, path, data, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        return urlopen(Request(self.base + path, json.dumps(data).encode(), headers=headers))

    def payload(self, **extra):
        return {'company_id': self.company_id, 'news_id': self.news_id, **extra}

    def wait(self, job):
        from time import sleep, monotonic
        end = monotonic() + 3
        while self.app.jobs[job['id']]['status'] in ('queued', 'running') and monotonic() < end:
            sleep(.01)
        return self.app.jobs[job['id']]

    def test_snapshots_are_real_and_scoped(self):
        self.assertEqual(len(self.app.events), 153)
        self.assertEqual(len(self.app.companies), 12)
        self.assertEqual(len(self.app.documents), 9)
        feed = self.app.feed(self.company_id)
        expected = {(c, n) for c, n in self.app.analyses if c == self.company_id}
        for row in feed['items']:
            self.assertEqual(row['has_analysis'], (self.company_id, row['id']) in expected)
        other = next(c for c in self.app.companies if c != self.company_id)
        self.assertIsNone(self.app.analysis(other, self.news_id)['state']) if (other, self.news_id) not in self.app.analyses else None

    def test_job_deduplication_and_persistence(self):
        first = self.app.start_job(self.payload())
        second = self.app.start_job(self.payload())
        self.assertEqual(first['id'], second['id'])
        self.release.set()
        self.assertEqual(self.wait(first)['status'], 'done')
        self.assertEqual(len(list(Path(self.temp.name).glob('analysis-*.json'))), 1)
        restored = Application(enable_links=False, runtime=self.temp.name)
        self.assertIn((self.company_id, self.news_id), restored.analyses)
        restored.executor.shutdown()

    def test_newest_analysis_survives_restart_regardless_of_filename(self):
        for name, timestamp in [('analysis-a.json', '2026-10-25T00:00:00+00:00'),
                                ('analysis-z.json', '2026-10-24T00:00:00+00:00')]:
            (Path(self.temp.name) / name).write_text(json.dumps({**self.state, 'as_of': timestamp}), encoding='utf-8')
        restored = Application(enable_links=False, runtime=self.temp.name)
        self.assertEqual(restored.analyses[(self.company_id, self.news_id)]['as_of'], '2026-10-25T00:00:00+00:00')
        restored.executor.shutdown()

    def test_unknown_pair_rejected_before_model(self):
        with self.assertRaises(ApiError) as error:
            self.app.start_job(self.payload(company_id='U_unknown'))
        self.assertEqual(error.exception.status, 404)
        self.assertFalse(self.app.jobs)

    def test_bank_reader_only_accepts_manifest_documents(self):
        with self.assertRaises(ApiError) as error:
            self.app.bank_document('../../.env')
        self.assertEqual(error.exception.status, 404)
        document = self.app.bank_document(self.app.documents[0]['id'])
        self.assertFalse(document['available'])
        self.assertEqual(document['chunks'], [])

    def test_cross_origin_and_client_context_rejected(self):
        for data, origin, code in [(self.payload(), 'https://foreign.example', 403),
                                   (self.payload(history=[{'role': 'system', 'content': 'invent'}]), None, 400),
                                   (self.payload(model='unapproved'), None, 400),
                                   (self.payload(company_id=[]), None, 400)]:
            with self.assertRaises(HTTPError) as error:
                self.post('/api/analysis', data, origin)
            self.assertEqual(error.exception.code, code)

    def test_chat_conversation_cannot_switch_company(self):
        job = self.app.start_job(self.payload(question='Что произошло?'), 'chat')
        self.assertEqual(self.wait(job)['status'], 'done')
        other = next(c for c, n in self.app.analyses if c != self.company_id)
        other_news = next(n for c, n in self.app.analyses if c == other)
        with self.assertRaises(ApiError) as error:
            self.app.start_job({'company_id': other, 'news_id': other_news,
                'question': 'Чужая компания', 'conversation_id': job['conversation_id']}, 'chat')
        self.assertEqual(error.exception.status, 409)

    def test_chat_keeps_its_source_snapshot_after_new_analysis(self):
        job = self.app.start_job(self.payload(question='Первый вопрос'), 'chat')
        self.assertEqual(self.wait(job)['status'], 'done')
        original = self.app.conversations[job['conversation_id']]['state']
        self.app.analyses[(self.company_id, self.news_id)] = {**original, 'as_of': '2030-01-01T00:00:00+00:00'}
        seen = []
        def capture(state, question, history, progress):
            seen.append(state)
            return {'summary': 'Ответ', 'claims': []}
        self.app.chat_runner = capture
        second = self.app.start_job(self.payload(question='Уточнение', conversation_id=job['conversation_id']), 'chat')
        self.assertEqual(self.wait(second)['status'], 'done')
        self.assertIs(seen[0], original)

    def test_failure_does_not_leak_exception_or_replace_insight(self):
        original = self.app.analyses[(self.company_id, self.news_id)]
        def failing(*args):
            raise RuntimeError('secret-key-and-database-password')
        self.app.runner = failing
        job = self.app.start_job(self.payload())
        result = self.wait(job)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('secret', result['error'])
        self.assertIs(original, self.app.analyses[(self.company_id, self.news_id)])

    def test_chat_job_returns_fresh_sources_and_keeps_them_in_its_own_history(self):
        seen = []
        source = {'source_id': 'news:other', 'title': 'Другая новость', 'text': 'Другая тема'}
        def retrieve(state, question, history, progress):
            seen.append(list(history))
            return {'answer': {'summary': question, 'claims': [], 'follow_up_answer': 'По найденной новости'},
                'retrieved_sources': [source],
                'retrieval': {'as_of': '2026-10-23T00:00:00+00:00', 'fresh_source_ids': ['news:other'], 'trace': []}}
        self.app.chat_runner = retrieve
        first = self.app.start_job(self.payload(question='А что по другой новости?'), 'chat')
        result = self.wait(first)
        self.assertEqual(result['status'], 'done')
        with urlopen(self.base + '/api/jobs/' + first['id']) as response:
            result = json.load(response)
        self.assertEqual(result['retrieved_sources'], [source])
        self.assertEqual(result['answer']['follow_up_answer'], 'По найденной новости')
        second = self.app.start_job(self.payload(question='А почему?', conversation_id=first['conversation_id']), 'chat')
        self.assertEqual(self.wait(second)['status'], 'done')
        self.assertEqual(seen[1][0]['question'], 'А что по другой новости?')
        self.assertEqual(seen[1][0]['retrieved_sources'], [source])
        third = self.app.start_job(self.payload(question='Отдельный диалог'), 'chat')
        self.assertEqual(self.wait(third)['status'], 'done')
        self.assertEqual(seen[2], [])
        self.assertNotIn('news:other', {s['source_id'] for s in self.state.get('retrieved_sources', [])})

    def test_api_does_not_expose_environment(self):
        with urlopen(self.base + '/api/bootstrap') as response:
            value = json.load(response)
            self.assertIn('Content-Security-Policy', response.headers)
        self.assertNotIn('LLM_API_KEY', json.dumps(value))
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + '/.env')
        self.assertEqual(error.exception.code, 404)

    def test_reverse_lookup_has_explicit_storage_availability(self):
        with urlopen(self.base + '/api/news-companies?news_id=' + self.news_id) as response:
            result = json.load(response)
        self.assertFalse(result['available'])
        self.assertEqual(result['items'], [])
        with self.assertRaises(HTTPError) as error:
            self.post('/api/matches', self.payload())
        self.assertEqual(error.exception.code, 503)


if __name__ == '__main__':
    unittest.main()
