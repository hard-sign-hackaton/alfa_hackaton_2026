import copy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent import offline_insight
from chat_agent import DatabaseChatAgent
from contracts import validate_evidence, Insight
from langchain_provider import ModelError
from retrieval import RetrievedSource
from run import AS_OF
from test_database_agent import RepositoryFixture, ClientFixture, bank_source, calls


def other_news(**updates):
    data = dict(source_id='news:another-publication', kind='news', title='Автокредиты',
        text='Выдача автокредитов сократилась.', published_at=AS_OF.isoformat(),
        locator='https://example.test/auto', url='https://example.test/auto')
    return RetrievedSource(**{**data, **updates})


class ChatAgentTests(unittest.TestCase):
    def setUp(self):
        self.repository = RepositoryFixture()
        self.company, self.news = self.repository.company, self.repository.news
        self.client = ClientFixture([])
        self.state = {'company_id': self.company.id, 'news_id': self.news.id,
            'company': self.company.model_dump(), 'event': self.news.model_dump(),
            'as_of': (AS_OF - timedelta(days=2)).isoformat(),
            'preparation': self.client.prepare(self.news).model_dump(),
            'result': offline_insight(self.company, self.news).model_dump(), 'retrieved_sources': []}

    def run_chat(self, client, question='Что происходит с автокредитами?', history=()):
        return DatabaseChatAgent(self.repository, client, as_of=AS_OF).run(self.state, question, history)

    def test_every_turn_searches_other_news_and_bank_and_model_can_refine(self):
        seen = []
        def search(query, **kwargs):
            seen.append((query, kwargs))
            return [other_news()] if query == 'автокредиты' else []
        client = ClientFixture([calls(('search_news', {'query': 'автокредиты'})), AIMessage(content='Enough')])
        with patch.object(self.repository, 'search_news', side_effect=search):
            turn = self.run_chat(client)
        self.assertEqual([item['tool'] for item in turn['retrieval']['trace']],
            ['search_news', 'search_bank_analytics', 'search_news'])
        self.assertEqual(turn['retrieval']['fresh_source_ids'], ['news:another-publication'])
        self.assertEqual(seen[0][1]['as_of'], AS_OF)
        self.assertEqual(seen[0][1]['exclude_id'], self.news.id)
        self.assertEqual(turn['answer']['news_id'], self.news.id)
        self.assertIn('news:another-publication', {e['source_id'] for c in turn['answer']['claims'] for e in c['evidence']})
        self.assertIn('автокредит', client.steps[0][1].content)
        validate_evidence(Insight.model_validate(turn['answer']), self.company, self.news, turn['retrieved_sources'])

    def test_demo_chat_uses_same_retrieval_but_keeps_fiction_explicit(self):
        self.state['is_demo'] = True
        client = ClientFixture([AIMessage(content='Enough')])
        turn = self.run_chat(client, 'Почему это касается нашей компании?')
        self.assertEqual([r['tool'] for r in turn['retrieval']['trace']], ['search_news', 'search_bank_analytics'])
        self.assertTrue(client.analyses[0]['news_metadata']['is_demo'])
        self.assertIn('вымышленный', client.steps[0][0].content)
        self.assertTrue(turn['answer']['follow_up_answer'].startswith('Тестовый сценарий.'))
        self.assertTrue(turn['retrieval']['is_demo'])

    def test_followup_retains_question_and_exact_previous_sources_without_mutating_analysis(self):
        original = copy.deepcopy(self.state)
        with patch.object(self.repository, 'search_news', return_value=[other_news()]):
            first = self.run_chat(ClientFixture([AIMessage(content='Enough')]))
        history = [{'question': 'Что происходит с автокредитами?', **first}]
        client = ClientFixture([AIMessage(content='Enough')])
        second = self.run_chat(client, 'А как это связано с нашей компанией?', history)
        self.assertIn('news:another-publication', {s['source_id'] for s in second['retrieved_sources']})
        planner_input = json.loads(client.steps[0][1].content)
        self.assertEqual(planner_input['history'][0]['question'], history[0]['question'])
        self.assertEqual(client.analyses[0]['history'][-1], first['answer'])
        self.assertEqual(client.analyses[0]['dialogue'][0]['question'], history[0]['question'])
        self.assertEqual(self.state, original)
        self.assertEqual(second['retrieval']['fresh_source_ids'], [])

    def test_planner_failure_still_uses_initial_search_and_reports_limitation(self):
        client = ClientFixture([])
        with patch.object(self.repository, 'search_news', return_value=[other_news()]), \
             patch.object(client, 'research_step', side_effect=ModelError('LLM transport failure')):
            turn = self.run_chat(client)
        self.assertEqual(turn['retrieval']['stop'], 'model_unavailable')
        self.assertEqual(turn['retrieval']['fresh_source_ids'], ['news:another-publication'])
        self.assertTrue(turn['retrieval']['limitations'])

    def test_tool_calls_are_bounded_and_private_scope_cannot_be_overridden(self):
        client = ClientFixture([calls(('get_company_metrics', {'company_id': 'other'}),
            ('execute_sql', {'sql': 'SELECT password'}),
            ('search_news', {'query': 'one'}), ('search_news', {'query': 'two'}),
            ('search_news', {'query': 'three'}))])
        turn = self.run_chat(client)
        self.assertEqual(len(turn['retrieval']['trace']), 6)
        self.assertEqual(turn['retrieval']['stop'], 'tool_limit')
        self.assertEqual([r['status'] for r in turn['retrieval']['trace'][2:4]], ['rejected', 'rejected'])
        self.assertNotIn(('news', 'three'), self.repository.queries)

    def test_unavailable_search_is_not_retried_and_exception_is_not_exposed(self):
        from database import DatabaseError
        client = ClientFixture([calls(('search_bank_analytics', {'query': 'another'})), AIMessage(content='Enough')])
        with patch.object(self.repository, 'search_bank_analytics', side_effect=DatabaseError('password=secret')) as read:
            turn = self.run_chat(client)
        self.assertEqual(read.call_count, 1)
        self.assertTrue(turn['retrieval']['trace'][-1]['cached'])
        self.assertNotIn('password', json.dumps(turn))

    def test_forged_answer_citation_is_rejected_after_model(self):
        client = ClientFixture([AIMessage(content='Enough')])
        result = offline_insight(self.company, self.news, 'Why?')
        result.claims[0].evidence[0].source_id = 'news:not-retrieved'
        with patch.object(client, 'analyze', return_value=result), self.assertRaises(ValueError):
            self.run_chat(client)

    def test_new_sources_take_priority_over_full_old_context(self):
        original = copy.deepcopy(self.state)
        original['retrieved_sources'] = [bank_source().model_copy(update={
            'source_id': 'bank:old-' + str(i), 'text': 'x' * 6000}).model_dump() for i in range(8)]
        self.state = original
        with patch.object(self.repository, 'search_news', return_value=[other_news()]):
            turn = self.run_chat(ClientFixture([AIMessage(content='Enough')]))
        self.assertEqual(turn['retrieved_sources'][0]['source_id'], 'news:another-publication')
        self.assertLessEqual(sum(len(s['text']) for s in turn['retrieved_sources']), 60000)

    def test_other_conversation_does_not_inherit_new_evidence(self):
        with patch.object(self.repository, 'search_news', return_value=[other_news()]):
            self.run_chat(ClientFixture([AIMessage(content='Enough')]))
        separate = self.run_chat(ClientFixture([AIMessage(content='Enough')]))
        self.assertEqual(separate['retrieved_sources'], [])

    def test_future_retrieval_is_rejected_and_not_forwarded(self):
        future = other_news(published_at=(AS_OF + timedelta(days=1)).isoformat())
        with patch.object(self.repository, 'search_news', return_value=[future]):
            turn = self.run_chat(ClientFixture([AIMessage(content='Enough')]))
        self.assertEqual(turn['retrieval']['trace'][0]['status'], 'rejected')
        self.assertEqual(turn['retrieved_sources'], [])


if __name__ == '__main__':
    unittest.main()
