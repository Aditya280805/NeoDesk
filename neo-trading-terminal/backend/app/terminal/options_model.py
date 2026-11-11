"""Per-run model completion budget and sanitized third-party logging."""
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field

from pydantic import SecretStr

from agno.models.openai import OpenAIChat
from app.terminal.agent_harness import bounded_invoke

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
        return 4096 if self.provider == 'gemini' else 900


def provider_settings(config):
    provider = config.options_agent_provider
    if provider == 'ollama':
        model = config.options_agent_model or 'qwen3:4b'
        error = 'Cloud model tags are disabled for local inference.' if 'cloud' in model.lower() else None
        return ProviderSettings('ollama', model, '', None, error)
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
        return BoundedOllamaChat(id=settings.model, api_key='ollama',
            base_url='http://127.0.0.1:11434/v1', max_tokens=900,
            timeout=30, max_retries=0)
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
    model = getattr(agent, 'model', None)
    if hasattr(model, 'aclose'):
        await model.aclose()


def provider_failure(config, error):
    """Map only known status codes; raw SDK error bodies can contain secrets."""
    from agno.exceptions import ModelProviderError
    provider = provider_settings(config)
    code = error.status_code if isinstance(error, ModelProviderError) else None
    name = {'gemini': 'Gemini', 'ollama': 'Ollama'}.get(provider.provider, 'OpenAI')
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

    async def ainvoke(self, *args, **kwargs):
        if self.completion_remaining <= 0 or self.requests_remaining <= 0:
            raise ValueError('Options model budget exhausted')
        self.requests_remaining -= 1
        self.max_completion_tokens = self.completion_remaining
        try:
            response = await bounded_invoke(super().ainvoke, self.completion_remaining, *args, **kwargs)
        except Exception as error:
            backup = self.key_rotator.next_key(error) if self.key_rotator else None
            if not backup or self.requests_remaining <= 0:
                raise
            if self.async_client is not None:
                await self.async_client.close()
                self.async_client = None
            self.api_key = backup.get_secret_value()
            self.requests_remaining -= 1
            response = await bounded_invoke(super().ainvoke, self.completion_remaining, *args, **kwargs)
        usage = response.response_usage
        # Missing usage: reserve the entire requested budget, never assume free.
        spent = getattr(usage, 'output_tokens', None)
        if spent is None:
            spent = self.completion_remaining
        self.completion_remaining -= max(0, spent)
        if self.completion_remaining < 0:
            raise ValueError('Options model exceeded completion budget')
        return response


@dataclass
class BoundedOllamaChat(BoundedOpenAIChat):
    """Ollama's local OpenAI-compatible endpoint uses max_tokens."""

    def get_request_params(self, *args, **kwargs):
        params = super().get_request_params(*args, **kwargs)
        params.pop('max_completion_tokens', None)
        params['max_tokens'] = self.completion_remaining
        return params
