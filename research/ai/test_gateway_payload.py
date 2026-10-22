import json
import unittest
import httpx
from langchain_core.messages import HumanMessage
from langchain_provider import LangChainClient
from model_config import GatewaySettings


class GatewayPayloadTests(unittest.TestCase):
    def test_sdk_sends_gateway_max_tokens_for_each_task(self):
        sent = []
        def respond(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json=dict(id='fixture', object='chat.completion', created=0,
                model=sent[-1]['model'], choices=[dict(index=0, finish_reason='stop',
                message=dict(role='assistant', content='{}'))], usage=dict(prompt_tokens=1, completion_tokens=1, total_tokens=2)))
        client = LangChainClient(settings=GatewaySettings.from_env({'LLM_API_KEY':'fixture'}))
        client._http_client = httpx.Client(transport=httpx.MockTransport(respond))
        try:
            for task in ('analysis', 'extraction', 'research'):
                client._model(task).invoke([HumanMessage(content='fixture')])
                self.assertEqual(sent[-1]['max_tokens'], client.settings.routes[task].max_tokens)
        finally:
            client.close()


if __name__ == '__main__': unittest.main()
