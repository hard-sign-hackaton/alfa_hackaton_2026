import json
import unittest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from fixtures import profiles, news
from grounding import fragment_catalog
from contracts import evidence_sources
from importance import assess
from langchain_provider import LangChainClient, ModelError


class ImportanceTests(unittest.TestCase):
    def setUp(self):
        self.company, self.news = profiles()[0], news()[0]

    def test_fast_route_resolves_exact_news_and_company_premises(self):
        calls = []
        def factory(route):
            calls.append(route.task)
            self.assertEqual(route.task, 'importance')
            def invoke(prompt):
                data = json.loads(prompt.to_messages()[1].content)
                return AIMessage(content=json.dumps({'level': 'medium', 'reason': 'Косвенная отраслевая связь.',
                    'news_fragment_id': next(iter(data['fragments'])),
                    'company_source_id': next(iter(data['company_sources']))}))
            return RunnableLambda(invoke)
        client = LangChainClient(model_factory=factory)
        result = assess(client, self.company, self.news)
        self.assertEqual(calls, ['importance'])
        sources = evidence_sources(self.company, self.news)
        for premise in result['evidence']:
            self.assertIn(premise['quote'], sources[premise['source_id']])

    def test_forged_fragment_is_rejected_with_bounded_retries(self):
        value = {'level': 'high', 'reason': 'Unknown', 'news_fragment_id': 'fake', 'company_source_id': 'foreign'}
        client = LangChainClient(model_factory=lambda route: RunnableLambda(lambda prompt: AIMessage(content=json.dumps(value))), sleeper=lambda _: None)
        with self.assertRaises(ModelError):
            assess(client, self.company, self.news)
        self.assertLessEqual(len(client.telemetry), 3)
