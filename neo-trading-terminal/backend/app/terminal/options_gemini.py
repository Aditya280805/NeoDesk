"""Native Gemini Developer API adapter with per-run generation limits."""
from dataclasses import dataclass, field
from collections import defaultdict, deque

from agno.models.google import Gemini
from google import genai
from google.genai import types


@dataclass
class BoundedGemini(Gemini):
    generation_remaining: int = 4096
    requests_remaining: int = 3
    _owns_client: bool = field(default=False, init=False, repr=False)
    key_rotator: object = field(default=None, repr=False)

    def _format_messages(self, messages, compress_tool_results=False):
        formatted, system = super()._format_messages(messages, compress_tool_results)
        call_ids, response_ids = defaultdict(deque), defaultdict(deque)
        for message in messages:
            if message.role == 'assistant':
                for call in message.tool_calls or []:
                    if call.get('id'):
                        call_ids[call['function']['name']].append(call['id'])
            elif message.role == 'tool' and message.tool_name and message.tool_call_id:
                response_ids[message.tool_name].append(message.tool_call_id)
        for content in formatted:
            for part in content.parts or []:
                if part.function_call and call_ids[part.function_call.name]:
                    part.function_call.id = call_ids[part.function_call.name].popleft()
                if part.function_response and response_ids[part.function_response.name]:
                    part.function_response.id = response_ids[part.function_response.name].popleft()
        return formatted, system

    def get_client(self):
        if self.client is None:
            # Explicit Developer API settings avoid accidentally using Vertex
            # credentials/billing from the machine's Google Cloud environment.
            self.client = genai.Client(api_key=self.api_key, vertexai=False, enterprise=False,
                http_options=types.HttpOptions(timeout=int((self.timeout or 30) * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1)))
            self._owns_client = True
        return self.client

    async def aclose(self):
        if self.client is not None and self._owns_client:
            try:
                await self.client.aio.aclose()
            finally:
                self.client.close()
                self.client = None
                self._owns_client = False

    def _get_metrics(self, usage):
        metrics = super()._get_metrics(usage)
        # Agno's Gemini adapter omits reasoning from its computed total. Keep
        # Google's authoritative total while displaying visible/thought counts.
        metrics.total_tokens = usage.total_token_count if usage.total_token_count is not None else (
            metrics.input_tokens + metrics.output_tokens + (metrics.reasoning_tokens or 0))
        return metrics

    async def ainvoke(self, *args, **kwargs):
        if self.generation_remaining <= 0 or self.requests_remaining <= 0:
            raise ValueError('Options Gemini generation budget exhausted')
        self.requests_remaining -= 1
        self.max_output_tokens = self.generation_remaining
        try:
            response = await super().ainvoke(*args, **kwargs)
        except Exception as error:
            backup = self.key_rotator.next_key(error) if self.key_rotator else None
            if not backup or self.requests_remaining <= 0:
                raise
            await self.aclose()
            self.api_key = backup.get_secret_value()
            self.requests_remaining -= 1
            response = await super().ainvoke(*args, **kwargs)
        usage = response.response_usage
        if usage is None or usage.output_tokens is None or usage.reasoning_tokens is None:
            spent = self.generation_remaining
        else:
            spent = usage.output_tokens + usage.reasoning_tokens
        self.generation_remaining -= max(0, spent)
        if self.generation_remaining < 0:
            raise ValueError('Options Gemini exceeded generation budget')
        return response
