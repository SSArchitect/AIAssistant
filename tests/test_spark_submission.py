"""Submission failures must not consume the six-hour accepted-task budget."""
import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import agent.aigc.spark_client as spark
from agent.aigc.progress import progress_scope
from agent.aigc.spark_video_client import SparkVideoClient
from agent.schemas.aigc import ImageGenerationRequest, VideoGenerationRequest


@pytest.fixture(params=[(spark.SparkImageClient, ImageGenerationRequest),
                        (SparkVideoClient, VideoGenerationRequest)], ids=['image', 'video'])
def media_client(request, tmp_path):
    client_type, request_type = request.param

    def create(handler, **kwargs):
        client = client_type('https://spark.test', 'secret-test-key', output_dir=tmp_path,
                             transport=httpx.MockTransport(handler), poll_interval=0, **kwargs)
        return client, request_type(prompt='rabbit hero', idempotency_key='original-key')
    return create


@pytest.mark.asyncio
async def test_background_connection_failure_stops_after_three_submission_attempts(media_client):
    requests, events = [], []

    def handler(request):
        requests.append(request)
        assert len(requests) <= 3, 'Unaccepted task was retried using the six-hour budget'
        raise httpx.ConnectError('DNS failed: secret-test-key')

    client, request = media_client(handler)
    with patch.object(spark.asyncio, 'sleep', new=AsyncMock()):
        with progress_scope(events.append, background=True):
            with pytest.raises(spark.SparkProviderError) as error:
                await client.generate(request)
    assert len(requests) == 3
    assert len({r.content for r in requests}) == 1
    assert {r.headers['idempotency-key'] for r in requests} == {'original-key'}
    assert error.value.context() == {'code': 'connection_failed', 'task_id': None,
                                     'idempotency_key': 'original-key'}
    assert all(e['stage'] != 'reconnecting' for e in events)
    assert events[-1]['stage'] == 'unknown'
    assert 'secret-test-key' not in str(error.value) + str(events)


@pytest.mark.asyncio
async def test_background_unacknowledged_submission_has_short_deadline(media_client, monkeypatch):
    # The watchdog makes the regression fail promptly even with the old six-hour loop.
    monkeypatch.setattr(spark, 'SUBMISSION_TIMEOUT', .01, raising=False)
    monkeypatch.setattr('agent.aigc.spark_video_client.VIDEO_SUBMISSION_TIMEOUT', .01)
    requests, events = [], []

    async def handler(request):
        requests.append(request)
        await asyncio.sleep(1)
        raise AssertionError('Submission deadline was not applied')

    client, request = media_client(handler, timeout=1)
    with progress_scope(events.append, background=True):
        with pytest.raises(spark.SparkProviderError) as error:
            await asyncio.wait_for(client.generate(request), .2)
    assert len(requests) == 1
    assert error.value.context() == {'code': 'wait_timeout', 'task_id': None,
                                     'idempotency_key': 'original-key'}
    assert [e['stage'] for e in events] == ['submitting', 'unknown']


@pytest.mark.asyncio
async def test_background_transient_submission_failure_recovers_with_original_key(tmp_path):
    from tests.test_spark_image import png, task

    requests, events = [], []

    def handler(request):
        if request.method == 'POST':
            requests.append(request)
            if len(requests) < 3:
                raise httpx.ConnectError('temporary failure')
            return httpx.Response(202, json=task())
        return httpx.Response(200, content=png(), headers={'Content-Type': 'image/png'})

    client = spark.SparkImageClient('https://spark.test', 'secret', output_dir=tmp_path,
                                    transport=httpx.MockTransport(handler))
    with patch.object(spark.asyncio, 'sleep', new=AsyncMock()):
        with progress_scope(events.append, background=True):
            result = await client.generate(ImageGenerationRequest(prompt='rabbit', idempotency_key='original-key'))
    assert result.id == 'task-123'
    assert len(requests) == 3
    assert len({r.content for r in requests}) == 1
    assert {r.headers['idempotency-key'] for r in requests} == {'original-key'}
    assert events[-1]['stage'] == 'completed'


@pytest.mark.asyncio
async def test_background_accepted_task_reconnects_without_resubmitting(tmp_path):
    from tests.test_spark_image import png, task

    posts, polls, events = [], [], []

    def handler(request):
        if request.method == 'POST':
            posts.append(request)
            return httpx.Response(202, json=task('queued'))
        if '/artifacts/' in request.url.path:
            return httpx.Response(200, content=png(), headers={'Content-Type': 'image/png'})
        polls.append(request)
        if len(polls) <= 3:
            raise httpx.ConnectError('temporary polling failure')
        return httpx.Response(200, json=task())

    client = spark.SparkImageClient('https://spark.test', 'secret', output_dir=tmp_path,
                                    transport=httpx.MockTransport(handler), poll_interval=0)
    with patch.object(spark.asyncio, 'sleep', new=AsyncMock()):
        with progress_scope(events.append, background=True):
            result = await client.generate(ImageGenerationRequest(prompt='rabbit', idempotency_key='original-key'))
    assert result.id == 'task-123'
    assert len(posts) == 1
    assert len(polls) == 4
    assert any(e['stage'] == 'reconnecting' and e['task_id'] == 'task-123' for e in events)
    assert events[-1]['stage'] == 'completed'
