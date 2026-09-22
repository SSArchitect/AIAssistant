import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest

from agent.aigc import creation_completion as completion
from agent.aigc.creation_models import PlanningOutputTruncated, planning_error
from agent.llm.base import LLMResponse, LLMStreamChunk


@pytest.mark.asyncio
async def test_stream_internal_error_retries_without_replaying_completed_work(monkeypatch):
    error = openai.APIError('SECRET upstream response', request=httpx.Request('POST', 'https://provider'),
        body={'error': {'code': 'InternalServerError', 'message': 'SECRET'}})
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[error, LLMResponse(content='{}')]))
    report = AsyncMock()
    sleep = AsyncMock()
    monkeypatch.setattr(completion.asyncio, 'sleep', sleep)
    result = await completion.PlanningCompletion(provider, report)([], {}, 'creation_node')
    assert result.content == '{}' and provider.chat.await_count == 2
    assert sleep.await_args.args == (1,)
    assert 'SECRET' not in str(report.call_args_list)
    assert planning_error(error)[0] == 'provider_unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['insufficient_quota', 'InvalidParameter', 'Unauthorized', 'unknown'])
async def test_stream_permanent_or_unknown_errors_are_not_retried(code):
    error = openai.APIError('SECRET', request=httpx.Request('POST', 'https://provider'), body={'code': code})
    provider = SimpleNamespace(chat=AsyncMock(side_effect=error))
    with pytest.raises(openai.APIError):
        await completion.PlanningCompletion(provider, AsyncMock())([], {}, 'creation_plan')
    assert provider.chat.await_count == 1


@pytest.mark.asyncio
async def test_active_but_endless_stream_closes_and_switches_to_partition(monkeypatch):
    monkeypatch.setattr(completion, 'MODEL_CALL_TIMEOUT', .015)
    closed = asyncio.Event()
    async def stream(*args, **kwargs):
        try:
            while True:
                yield LLMStreamChunk(reasoning='still thinking')
                await asyncio.sleep(.002)
        finally:
            closed.set()
    provider = SimpleNamespace(chat_stream_response=stream)
    report = AsyncMock()
    call = completion.PlanningCompletion(provider, report, streaming=True)
    with pytest.raises(PlanningOutputTruncated):
        await call([], {}, 'creation_plan')
    assert closed.is_set() and call.transport_retries == 0
    assert any(c.args[0] == 'model_timeout' for c in report.call_args_list)


@pytest.mark.asyncio
async def test_cancelled_planning_call_does_not_retry_and_closes_child():
    entered, closed = asyncio.Event(), asyncio.Event()
    async def chat(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
    call = completion.PlanningCompletion(SimpleNamespace(chat=chat), AsyncMock())
    task = asyncio.create_task(call([], {}, 'creation_plan'))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and call.transport_retries == 0


def test_dependency_diagnostic_identifies_offending_node():
    from agent.aigc.creation_planning import CreativePlan
    from tests.test_creation_planning import plan
    value = plan()
    value['nodes'][1]['depends_on'].append('missing_scene')
    with pytest.raises(ValueError, match='video.*missing_scene'):
        CreativePlan.model_validate(value)


@pytest.mark.asyncio
async def test_slow_full_graph_recovers_via_partition_without_losing_nodes(monkeypatch):
    from agent.aigc import creation_planning as planning
    from tests.test_creation_partition import manifest
    from tests.test_creation_planning import plan, request
    monkeypatch.setattr(completion, 'MODEL_CALL_TIMEOUT', .03)
    value = plan()
    answers = [None, manifest(value['nodes']), *[dict(node=n) for n in value['nodes']]]
    closed = []
    async def stream(*args, **kwargs):
        answer = answers.pop(0)
        try:
            if answer is None:
                yield LLMStreamChunk(reasoning='thinking')
                await asyncio.Event().wait()
            yield LLMStreamChunk(response=LLMResponse(content=json.dumps(answer), model='test'))
        finally:
            closed.append(True)
    monkeypatch.setattr(planning, 'create_provider', lambda: SimpleNamespace(chat_stream_response=stream))
    events = []
    async def report(event): events.append(event)
    result = await planning.propose_creation(request(), on_progress=report)
    assert [n.id for n in result.plan.nodes] == ['script', 'video']
    assert len(closed) == 4 and not answers
    assert any(e['stage'] == 'partition' for e in events)
