"""Per-run model completion budget and sanitized third-party logging."""
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr

from agno.models.openai import OpenAIChat
from app.terminal.agent_harness import bounded_invoke, bounded_stream

OLLAMA_DEFAULT_MODEL = 'qwen3.5:9b-q4_K_M'
OLLAMA_DEFAULT_BASE_URL = 'http://localhost:11434/v1'
OLLAMA_DEFAULT_API_KEY = 'ollama'

options_run = ContextVar('options_run', default=False)


@dataclass(repr=False)
class KeyRotator:
    primary: SecretStr | None = field(repr=False)
    backup: SecretStr | None = field(default=None, repr=False)
    used: bool = False

    def next_key(self, error):
        from agno.exceptions import ModelProviderError
        if not isinstance(error, ModelProviderError) or error.status_code != 429 or self.used:
            return None
        self.used = True
        if not self.backup or not self.backup.get_secret_value().strip():
            return None
        if self.primary and self.backup.get_secret_value() == self.primary.get_secret_value():
            return None
        return self.backup


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    model: str
    key_name: str
    key: SecretStr | None = field(repr=False)
    error: str | None = None

    @property
    def configured(self):
        if self.provider == 'ollama':
            return not self.error
        return bool(self.key and self.key.get_secret_value().strip() and not self.error)

    @property
    def token_budget(self):
        return 4096 if self.provider in ('gemini', 'ollama') else 900


def ollama_tags_url(base_url: str | None = None) -> str:
    """Return the local Ollama /api/tags health endpoint for a configured loopback base URL."""
    raw = (base_url or OLLAMA_DEFAULT_BASE_URL).strip().rstrip('/')
    parsed = urlparse(raw)
    if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'} or not parsed.netloc:
        raise ValueError('Ollama base URL must be an http loopback URL (localhost, 127.0.0.1, or ::1).')
    return f'{parsed.scheme}://{parsed.netloc}/api/tags'


async def check_ollama_health(config, *, http_client=None, timeout: float = 3.0) -> dict:
    """Ping local Ollama /api/tags and verify the configured model is available."""
    settings = provider_settings(config)
    if settings.provider != 'ollama':
        return {
            'status': 'skipped',
            'healthy': True,
            'provider': settings.provider,
            'url': None,
            'model': settings.model,
            'model_available': None,
            'available_models': [],
            'error': None,
        }
    try:
        url = ollama_tags_url(getattr(config, 'ollama_base_url', None))
    except ValueError as exc:
        return {
            'status': 'invalid_config',
            'healthy': False,
            'provider': 'ollama',
            'url': None,
            'model': settings.model,
            'model_available': False,
            'available_models': [],
            'error': str(exc),
        }
    try:
        if http_client is not None:
            response = await http_client.get(url, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
        if response.status_code != 200:
            return {
                'status': 'error',
                'healthy': False,
                'provider': 'ollama',
                'url': url,
                'model': settings.model,
                'model_available': False,
                'available_models': [],
                'error': f'Ollama health check returned HTTP {response.status_code} from {url}.',
            }
        payload = response.json()
        raw_models = payload.get('models') if isinstance(payload, dict) else []
        available = [
            str(entry.get('name') or entry.get('model'))
            for entry in (raw_models or [])
            if isinstance(entry, dict) and (entry.get('name') or entry.get('model'))
        ]
        target = settings.model
        model_available = target in available or (':' not in target and f'{target}:latest' in available)
        return {
            'status': 'ok' if model_available else 'missing_model',
            'healthy': model_available,
            'provider': 'ollama',
            'url': url,
            'model': target,
            'model_available': model_available,
            'available_models': available,
            'error': None if model_available else f"Configured Ollama model '{target}' not found at {url}.",
        }
    except Exception as exc:
        return {
            'status': 'unreachable',
            'healthy': False,
            'provider': 'ollama',
            'url': url,
            'model': settings.model,
            'model_available': False,
            'available_models': [],
            'error': f'Ollama health check failed at {url}: {type(exc).__name__}',
        }


def provider_settings(config):
    provider = config.options_agent_provider
    if provider == 'ollama':
        model = config.options_agent_model or OLLAMA_DEFAULT_MODEL
        error = 'Cloud model tags are disabled for local inference.' if 'cloud' in model.lower() else None
        api_key = getattr(config, 'ollama_api_key', None) or SecretStr(OLLAMA_DEFAULT_API_KEY)
        return ProviderSettings('ollama', model, 'OLLAMA_API_KEY', api_key, error)
    if provider == 'auto':
        if config.gemini_api_key and config.gemini_api_key.get_secret_value().strip():
            provider = 'gemini'
        elif config.openai_api_key and config.openai_api_key.get_secret_value().strip():
            provider = 'openai'
        else:
            provider = 'gemini'
    gemini = provider == 'gemini'
    model = config.options_agent_model or ('gemini-3.8-flash' if gemini else 'gpt-4.1-mini')
    key_name = 'GEMINI_API_KEY' if gemini else 'OPENAI_API_KEY'
    key = config.gemini_api_key if gemini else config.openai_api_key
    error = None
    if gemini != model.startswith('gemini-'):
        error = f'OPTIONS_AGENT_MODEL does not match {provider}. Select a {provider} model and restart the backend.'
    return ProviderSettings(provider, model, key_name, key, error)


def build_model(config):
    settings = provider_settings(config)
    if not settings.configured:
        raise ValueError(settings.error or f'Set {settings.key_name} on the server.')
    if settings.provider == 'ollama':
        base_url = getattr(config, 'ollama_base_url', None) or OLLAMA_DEFAULT_BASE_URL
        api_key = (settings.key.get_secret_value().strip() if settings.key else '') or OLLAMA_DEFAULT_API_KEY
        timeout = getattr(config, 'ollama_timeout_seconds', 90)
        reasoning_effort = getattr(config, 'ollama_reasoning_effort', 'none')
        extra_kwargs = {'reasoning_effort': reasoning_effort} if reasoning_effort is not None else {}
        return BoundedOllamaChat(
            id=settings.model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=settings.token_budget,
            timeout=timeout,
            max_retries=0,
            completion_remaining=settings.token_budget,
            **extra_kwargs,
        )
    backup = config.gemini_backup_api_key if settings.provider == 'gemini' else config.openai_backup_api_key
    rotator = KeyRotator(settings.key, backup)
    if settings.provider == 'gemini':
        from app.terminal.options_gemini import BoundedGemini
        return BoundedGemini(id=settings.model, api_key=settings.key.get_secret_value(),
                             timeout=30, max_output_tokens=4096,
                             thinking_level='low', retries=0, retry_with_guidance=False, key_rotator=rotator)
    return BoundedOpenAIChat(id=settings.model, api_key=settings.key.get_secret_value(),
                            max_completion_tokens=900, timeout=30, max_retries=0, key_rotator=rotator)


async def close_agent_model(agent):
    seen = set()
    targets = [getattr(agent, 'model', None)]
    for member in getattr(agent, 'members', None) or ():
        targets.append(getattr(member, 'model', None))
    for model in targets:
        if model is None or id(model) in seen:
            continue
        seen.add(id(model))
        if hasattr(model, 'aclose'):
            await model.aclose()


def provider_failure(config, error):
    """Map only known status codes; raw SDK error bodies can contain secrets."""
    from agno.exceptions import ModelProviderError
    provider = provider_settings(config)
    code = error.status_code if isinstance(error, ModelProviderError) else None
    name = {'gemini': 'Gemini', 'ollama': 'Ollama'}.get(provider.provider, 'OpenAI')
    if code == 503:
        return 'provider_busy', f'{name} is busy. Wait for the current request to finish and retry.'
    if code == 429:
        return 'provider_quota', f'{name} quota or rate limit reached. Check your API project limits and retry later.'
    if code == 401:
        return 'provider_auth', f'{name} could not authenticate. Check {provider.key_name} on the server and restart.'
    if code == 403:
        return 'provider_permission', f'{name} denied permission. Check model access and API project eligibility.'
    if code == 404:
        return 'provider_model', f'{name} model is unavailable. Check OPTIONS_AGENT_MODEL and project access.'
    return 'model_or_output', 'The AI service could not answer with validated evidence. Check the model/key configuration or retry later.'


class OptionsLogFilter(logging.Filter):
    def filter(self, record):
        if options_run.get():
            record.msg = 'Options agent provider event (details suppressed; inspect options run trace).'
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


# This terminal's Agno integration uses the agent logger. ContextVar keeps other
# callers' logging intact while preventing SDK exception bodies entering logs.
from agno.utils.log import agent_logger
agent_logger.addFilter(OptionsLogFilter())


@dataclass
class BoundedOpenAIChat(OpenAIChat):
    completion_remaining: int = 900
    requests_remaining: int = 3
    key_rotator: KeyRotator | None = field(default=None, repr=False)

    def _reserve_budget(self):
        if self.completion_remaining <= 0 or self.requests_remaining <= 0:
            raise ValueError('Options model budget exhausted')
        self.requests_remaining -= 1
        self.max_completion_tokens = self.completion_remaining

    def _consume_usage(self, usage):
        # Missing usage: reserve the entire requested budget, never assume free.
        spent = getattr(usage, 'output_tokens', None)
        if spent is None:
            spent = self.completion_remaining
        self.completion_remaining -= max(0, spent)
        if self.completion_remaining < 0:
            raise ValueError('Options model exceeded completion budget')

    async def _rotate_backup_key(self, error):
        backup = self.key_rotator.next_key(error) if self.key_rotator else None
        if not backup or self.requests_remaining <= 0:
            return False
        await self.aclose()
        self.api_key = backup.get_secret_value()
        self.requests_remaining -= 1
        return True

    async def ainvoke(self, *args, **kwargs):
        self._reserve_budget()
        base_invoke = super().ainvoke
        try:
            response = await bounded_invoke(base_invoke, self.completion_remaining, *args, **kwargs)
        except Exception as error:
            if not await self._rotate_backup_key(error):
                raise
            response = await bounded_invoke(base_invoke, self.completion_remaining, *args, **kwargs)
        self._consume_usage(response.response_usage)
        return response

    async def ainvoke_stream(self, *args, **kwargs):
        self._reserve_budget()
        base_stream = super().ainvoke_stream
        final_usage = None
        yielded = False
        try:
            async for delta in bounded_stream(base_stream, self.completion_remaining, *args, **kwargs):
                yielded = True
                if getattr(delta, 'response_usage', None) is not None:
                    final_usage = delta.response_usage
                yield delta
        except Exception as error:
            if yielded or not await self._rotate_backup_key(error):
                raise
            async for delta in bounded_stream(base_stream, self.completion_remaining, *args, **kwargs):
                if getattr(delta, 'response_usage', None) is not None:
                    final_usage = delta.response_usage
                yield delta
        self._consume_usage(final_usage)

    async def aclose(self):
        if self.async_client is not None:
            client, self.async_client = self.async_client, None
            await client.close()


@dataclass
class BoundedOllamaChat(BoundedOpenAIChat):
    """Ollama's local OpenAI-compatible endpoint uses max_tokens."""

    completion_remaining: int = 4096
    role_map: dict[str,str] | None = field(default_factory=lambda:{**OpenAIChat.default_role_map,'system':'system'})

    def get_request_params(self, *args, **kwargs):
        params = super().get_request_params(*args, **kwargs)
        params.pop('max_completion_tokens', None)
        params['max_tokens'] = self.completion_remaining
        return params
