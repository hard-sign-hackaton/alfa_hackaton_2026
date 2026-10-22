"""Gateway settings and task-specific model selection."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ALLOWED_MODELS = frozenset({
    'google/gemma-4-26b-a4b-it', 'z-ai/glm-5.3-flash', 'qwen/qwen3.6-35b-a3b',
    'deepseek/deepseek-v4.1-flash', 'qwen/qwen3-vl-30b-a3b-instruct', 'moonshotai/kimi-k2.6',
})
DEFAULT_ROUTES = {
    'brief': ('LLM_BRIEF_MODEL', 'google/gemma-4-26b-a4b-it', 2048),
    'research': ('LLM_RESEARCH_MODEL', 'deepseek/deepseek-v4.1-flash', 2048),
    'classification': ('LLM_CLASSIFICATION_MODEL', 'google/gemma-4-26b-a4b-it', 1024),
    'extraction': ('LLM_EXTRACTION_MODEL', 'qwen/qwen3.6-35b-a3b', 4096),
    'analysis': ('LLM_ANALYSIS_MODEL', 'deepseek/deepseek-v4.1-flash', 6144),
    'chat': ('LLM_CHAT_MODEL', 'z-ai/glm-5.3-flash', 4096),
}


def load_environment():
    load_dotenv(Path(__file__).resolve().parents[2] / '.env', override=False)


@dataclass(frozen=True)
class ModelRoute:
    task: str
    model: str
    max_tokens: int


@dataclass(frozen=True)
class GatewaySettings:
    api_key: str = field(default='', repr=False)
    base_url: str = 'https://changellenge.up.railway.app/v1'
    timeout: float = 120.0
    routes: dict[str, ModelRoute] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        base_url = env.get('LLM_BASE_URL', cls.base_url).rstrip('/')
        parsed = urlparse(base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('LLM_BASE_URL must be an HTTPS API URL without credentials or query parameters')
        timeout = float(env.get('LLM_REQUEST_TIMEOUT', '120'))
        if not 1 <= timeout <= 300:
            raise ValueError('LLM_REQUEST_TIMEOUT must be between 1 and 300 seconds')
        routes = {}
        for task, (variable, default, tokens) in DEFAULT_ROUTES.items():
            model = env.get(variable, default)
            if model not in ALLOWED_MODELS:
                raise ValueError(f'{variable} must name an approved model')
            routes[task] = ModelRoute(task, model, tokens)
        return cls(api_key=env.get('LLM_API_KEY', ''), base_url=base_url, timeout=timeout, routes=routes)

    def signature(self):
        return {'base_url': self.base_url, 'models': {task: route.model for task, route in self.routes.items()}}
