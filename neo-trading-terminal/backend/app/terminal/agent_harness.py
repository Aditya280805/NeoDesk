"""Request-local cumulative budgets. No evidence is retained in diagnostics."""
import asyncio
import json
import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


class HarnessError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def estimate_tokens(value):
    """Conservative UTF-8 byte estimate, not provider tokenizer usage."""
    def encode(obj):
        from agno.models.message import Message
        if isinstance(obj, Message):
            return obj.model_dump(mode='json', exclude_none=True, exclude={'metrics', 'references'})
        if hasattr(obj, 'model_dump'):
            return obj.model_dump(mode='json', exclude_none=True)
        raise TypeError('Unsupported context object')
    return math.ceil(len(json.dumps(value, default=encode, ensure_ascii=False).encode('utf-8')) / 3)


def bounded_context(required, history, *, input_limit=24000):
    retained = list(history[-4:])
    while retained and estimate_tokens([required, retained]) > input_limit:
        retained.pop(0)
    if estimate_tokens([required, retained]) > input_limit:
        raise HarnessError('context_budget')
    return required, retained


@dataclass
class StageBudget:
    generation_limit: int
    input_token_estimate: int = 0
    attempts: int = 0
    generation_spent: int = 0
    reported_output: int = 0
    unknown_usage: int = 0
    duration_ms: float = 0


@dataclass
class RequestHarness:
    auto: bool = False
    deadline: float | None = None
    input_limit: int = 24000
    context_limit: int = 32768
    attempts: int = 0
    tool_reads: int = 0
    broker_fetches: int = 0
    cache_hits: int = 0
    delegations: int = 0
    admission_owner: object = field(default=None, repr=False)
    stages: dict[str, StageBudget] = field(default_factory=dict)

    def __post_init__(self):
        if self.deadline is None:
            self.deadline = time.monotonic() + (85 if self.auto else 60)

    @property
    def deadline_monotonic(self):
        return self.deadline

    def check_deadline(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise HarnessError('timeout')
        return remaining

    def reserve(self, stage, generation_limit, input_estimate):
        self.check_deadline()
        if stage not in ('router', 'specialist') or (stage == 'router' and not self.auto):
            raise HarnessError('routing')
        budget = self.stages.setdefault(stage, StageBudget(generation_limit))
        allowance = min(generation_limit, budget.generation_limit-budget.generation_spent)
        if input_estimate > self.input_limit or input_estimate + allowance > self.context_limit:
            raise HarnessError('context_budget')
        if allowance <= 0 or budget.attempts >= 3 or self.attempts >= (6 if self.auto else 3):
            raise HarnessError('model_budget')
        self.attempts += 1
        budget.attempts += 1
        budget.input_token_estimate += input_estimate
        budget.generation_spent += allowance
        return budget, allowance

    def account(self, ticket, spent):
        budget, allowance = ticket
        if spent is None:
            budget.unknown_usage += 1
            return
        spent = max(0, int(spent))
        budget.generation_spent += spent-allowance
        budget.reported_output += spent
        if budget.generation_spent > budget.generation_limit:
            raise HarnessError('model_budget')
        self.check_deadline()

    def read_tool(self):
        self.check_deadline()
        if self.tool_reads >= 3:
            raise HarnessError('tool_budget')
        self.tool_reads += 1

    def trace(self):
        # Construct from allowlisted numeric fields; never accept arbitrary
        # provider metadata, errors, prompts or evidence in this export.
        return {'attempts': self.attempts, 'tool_reads': self.tool_reads,
            'broker_fetches': self.broker_fetches, 'cache_hits': self.cache_hits,
            'delegations': self.delegations,
            'token_estimate_method': 'utf8-bytes-divided-by-3',
            'stages': {name: {'attempts': value.attempts,
                'generation_spent': value.generation_spent,
                'input_token_estimate': value.input_token_estimate,
                'reported_output': value.reported_output,
                'unknown_usage': value.unknown_usage,
                'duration_ms': round(value.duration_ms, 3)}
                for name, value in self.stages.items()}}


current_harness = ContextVar('agent_harness', default=None)


@contextmanager
def harness_context(harness, stage):
    token = current_harness.set((harness, stage))
    try:
        yield harness
    finally:
        current_harness.reset(token)


def _prepare_bounded_invocation(invoke, generation_limit, args, kwargs):
    active = current_harness.get()
    if active is None:
        return None
    harness, stage = active
    request = {name: kwargs[name] for name in ('messages', 'tools', 'response_format', 'tool_choice') if name in kwargs}
    if args:
        request['positional'] = args
    # Pydantic schema classes are serialized as schemas, never as object reprs.
    schema = request.get('response_format')
    if isinstance(schema, type) and hasattr(schema, 'model_json_schema'):
        request['response_format'] = schema.model_json_schema()
    input_estimate = estimate_tokens(request)
    if input_estimate * 3 > 65536:
        raise HarnessError('context_budget')
    ticket = harness.reserve(stage, generation_limit, input_estimate)
    owner = getattr(invoke, '__self__', None)
    if owner is not None:
        for name in ('completion_remaining', 'generation_remaining', 'max_completion_tokens', 'max_output_tokens', 'max_tokens'):
            value = getattr(owner, name, None)
            if isinstance(value, int):
                setattr(owner, name, min(value, ticket[1]))
    return harness, ticket


def _account_bounded_usage(harness, ticket, usage, *, reasoning=False):
    spent = getattr(usage, 'output_tokens', None)
    if reasoning:
        thoughts = getattr(usage, 'reasoning_tokens', None)
        spent = None if spent is None or thoughts is None else spent + thoughts
    harness.account(ticket, spent)


async def bounded_invoke(invoke, generation_limit, *args, reasoning=False, **kwargs):
    prepared = _prepare_bounded_invocation(invoke, generation_limit, args, kwargs)
    if prepared is None:
        return await invoke(*args, **kwargs)
    harness, ticket = prepared
    started = time.monotonic()
    try:
        async with asyncio.timeout(harness.check_deadline()):
            response = await invoke(*args, **kwargs)
    except TimeoutError:
        harness.account(ticket, None)
        raise HarnessError('timeout') from None
    except BaseException as error:
        from agno.exceptions import ModelProviderError
        # An explicit quota rejection precedes generation. Transport errors and
        # cancellation have unknown usage and keep their full reservation.
        rejected = isinstance(error, ModelProviderError) and error.status_code == 429
        harness.account(ticket, 0 if rejected else None)
        raise
    finally:
        ticket[0].duration_ms += (time.monotonic()-started)*1000
    _account_bounded_usage(harness, ticket, getattr(response, 'response_usage', None), reasoning=reasoning)
    return response


async def bounded_stream(invoke_stream, generation_limit, *args, reasoning=False, **kwargs):
    prepared = _prepare_bounded_invocation(invoke_stream, generation_limit, args, kwargs)
    if prepared is None:
        async for delta in invoke_stream(*args, **kwargs):
            yield delta
        return
    harness, ticket = prepared
    started = time.monotonic()
    final_usage = None
    completed = False
    try:
        async with asyncio.timeout(harness.check_deadline()):
            async for delta in invoke_stream(*args, **kwargs):
                usage = getattr(delta, 'response_usage', None)
                if usage is not None:
                    final_usage = usage
                yield delta
        completed = True
    except TimeoutError:
        harness.account(ticket, None)
        raise HarnessError('timeout') from None
    except BaseException as error:
        from agno.exceptions import ModelProviderError
        rejected = isinstance(error, ModelProviderError) and error.status_code == 429
        harness.account(ticket, 0 if rejected else None)
        raise
    finally:
        ticket[0].duration_ms += (time.monotonic()-started)*1000
    if completed:
        _account_bounded_usage(harness, ticket, final_usage, reasoning=reasoning)
