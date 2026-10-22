from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from agent import ResearchAgent, offline_insight
from contracts import Claim, Evidence
from fixtures import profiles, news
from model_config import GatewaySettings, ALLOWED_MODELS
from provider import LangChainClient, ModelError
from run import AS_OF, run
from tasks import TopicClassification, EventExtraction


class ModelRoutingTests(unittest.TestCase):
    def setUp(self):
        self.companies, self.events = profiles(), news()
        self.event = self.events[0]
        self.calls = []
        self.settings = GatewaySettings.from_env({})

    def factory(self, route):
        def invoke(prompt):
            data = json.loads(prompt.to_messages()[1].content)
            self.calls.append((route.task, route.model, data))
            evidence = Evidence(source_id=f'news:{self.event.id}', quote=self.event.title)
            if route.task == 'classification':
                result = TopicClassification(news_id=self.event.id, business_relevant=True,
                                             topics=['metallurgy'], evidence=[evidence])
            elif route.task == 'extraction':
                result = EventExtraction(news_id=self.event.id,
                                         facts=[Claim(kind='fact', text=self.event.title, evidence=[evidence])],
                                         missing_data=[])
            else:
                company = next(item for item in self.companies if item.id == data['company_id'])
                result = offline_insight(company, self.event, data['question'])
            return AIMessage(content=result.model_dump_json(), response_metadata={'finish_reason': 'stop'},
                             usage_metadata={'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30})
        return RunnableLambda(invoke)

    def client(self, **kwargs):
        return LangChainClient(settings=self.settings, model_factory=self.factory, **kwargs)

    def test_four_tasks_use_distinct_models_and_receive_preparation(self):
        client = self.client()
        prepared = client.prepare(self.event)
        insight = client.analyze(self.companies[0], self.event, preparation=prepared)
        answer = client.analyze(self.companies[0], self.event, preparation=prepared,
                                question='Каких данных не хватает?', history=[insight.model_dump()])
        self.assertEqual([call[0] for call in self.calls], ['classification', 'extraction', 'analysis', 'chat'])
        self.assertEqual(len({call[1] for call in self.calls}), 4)
        self.assertIn('preparation', self.calls[2][2])
        self.assertEqual(self.calls[3][2]['history'][0]['company_id'], self.companies[0].id)
        self.assertTrue(answer.follow_up_answer)
        self.assertTrue(all(metric['status'] == 'validated_references' for metric in client.telemetry))

    def test_preparation_is_shared_across_companies_without_sharing_analysis(self):
        client = self.client()
        for company in self.companies:
            ResearchAgent(self.companies, self.events, client=client, as_of=AS_OF).run(
                company.id, self.event.id, question='Что проверить?')
        self.assertEqual([call[0] for call in self.calls].count('classification'), 1)
        self.assertEqual([call[0] for call in self.calls].count('extraction'), 1)
        analyses = [data for task, model, data in self.calls if task == 'analysis']
        self.assertEqual({item['company_id'] for item in analyses}, {company.id for company in self.companies})
        self.assertEqual(len(self.calls), 6)

    def test_changed_publication_invalidates_preparation_cache(self):
        client = self.client()
        prepared = client.prepare(self.event)
        prepared.classification.topics[:] = ['other_business']
        self.assertEqual(client.prepare(self.event).classification.topics, ['metallurgy'])
        client.prepare(self.event.model_copy(update={'text': self.event.text + '\nДополнение.'}))
        self.assertEqual(len(self.calls), 4)

    def test_non_business_publication_skips_remaining_models(self):
        def factory(route):
            self.assertEqual(route.task, 'classification')
            value = TopicClassification(news_id=self.event.id, business_relevant=False,
                                        topics=['not_business'], evidence=[Evidence(
                                            source_id=f'news:{self.event.id}', quote=self.event.title)])
            return RunnableLambda(lambda prompt: AIMessage(content=value.model_dump_json()))
        client = LangChainClient(settings=self.settings, model_factory=factory)
        state = ResearchAgent(self.companies, self.events, client=client, as_of=AS_OF).run(
            self.companies[0].id, self.event.id)
        self.assertEqual(state['trace'][-1]['tool'], 'skip_analysis')
        self.assertEqual(len(client.telemetry), 1)

    def test_invalid_extraction_citations_are_rejected(self):
        result = EventExtraction(news_id=self.event.id, facts=[Claim(kind='fact', text='Unknown',
                                 evidence=[Evidence(source_id='news:wrong', quote='Unknown')])], missing_data=[])
        client = LangChainClient(settings=self.settings, model_factory=lambda route: RunnableLambda(
            lambda prompt: AIMessage(content=result.model_dump_json())))
        with self.assertRaises(ModelError):
            client.extract(self.event)
        self.assertEqual(len(client.telemetry), 2)

    def test_foreign_history_is_rejected_before_model_call(self):
        client = self.client()
        prior = offline_insight(self.companies[1], self.event).model_dump()
        with self.assertRaises(ValueError):
            client.analyze(self.companies[0], self.event, question='Почему?', history=[prior])
        self.assertEqual(self.calls, [])

    def test_checkpoint_rejects_different_model_routes(self):
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder) / 'state.json'
            ResearchAgent(self.companies, self.events, client=self.client(), as_of=AS_OF,
                          checkpoint=checkpoint).run(self.companies[0].id, self.event.id)
            settings = GatewaySettings.from_env({'LLM_ANALYSIS_MODEL': 'moonshotai/kimi-k2.6'})
            client = LangChainClient(settings=settings, model_factory=self.factory)
            with self.assertRaises(ValueError):
                ResearchAgent(self.companies, self.events, client=client, as_of=AS_OF,
                              checkpoint=checkpoint).run(self.companies[0].id, self.event.id, resume=True)

    def test_only_approved_models_can_be_selected(self):
        for model in ('deepseek-v4-pro', 'deepseek-cost-test', 'unknown'):
            with self.assertRaises(ValueError):
                GatewaySettings.from_env({'LLM_ANALYSIS_MODEL': model})
        selected = GatewaySettings.from_env({'LLM_CHAT_MODEL': 'moonshotai/kimi-k2.6'})
        self.assertIn(selected.routes['chat'].model, ALLOWED_MODELS)

    def test_api_key_is_not_in_configuration_repr_or_signature(self):
        settings = GatewaySettings.from_env({'LLM_API_KEY': 'private-test-value'})
        self.assertNotIn('private-test-value', repr(settings))
        self.assertNotIn('private-test-value', json.dumps(settings.signature()))

    def test_provider_error_does_not_log_response_body_or_credentials(self):
        class Forbidden(Exception):
            status_code = 403
        def invoke(prompt):
            raise Forbidden('private-test-value')
        client = LangChainClient(settings=self.settings,
                                 model_factory=lambda route: RunnableLambda(invoke))
        with self.assertRaisesRegex(ModelError, 'LLM HTTP 403'):
            client.classify(self.event)
        self.assertNotIn('private-test-value', json.dumps(client.telemetry))
        self.assertEqual(len(client.telemetry), 1)

    def test_sdk_truncation_retries_once_with_larger_budget(self):
        budgets = []
        class LengthFinishReasonError(Exception):
            pass
        def factory(route):
            budgets.append(route.max_tokens)
            if len(budgets) == 1:
                def truncated(prompt):
                    raise LengthFinishReasonError()
                return RunnableLambda(truncated)
            return self.factory(route)
        client = LangChainClient(settings=self.settings, model_factory=factory)
        client.extract(self.event)
        self.assertEqual(budgets[1], budgets[0] * 2)
        self.assertEqual(client.telemetry[0]['status'], 'truncated')
        self.assertEqual(client.telemetry[1]['status'], 'validated_references')

    def test_missing_key_does_not_create_live_results(self):
        with tempfile.TemporaryDirectory() as folder, patch('run.load_environment'), patch.dict('os.environ', {}, clear=True):
            destination = Path(folder) / 'live'
            with self.assertRaises(ModelError):
                run('live', destination)
            self.assertFalse(destination.exists())

    def test_insecure_or_credential_bearing_endpoint_is_rejected(self):
        for endpoint in ('http://gateway.example/v1', 'https://user:password@gateway.example/v1',
                         'https://gateway.example/v1?api_key=private'):
            with self.assertRaises(ValueError):
                GatewaySettings.from_env({'LLM_BASE_URL': endpoint})


if __name__ == '__main__':
    unittest.main()
