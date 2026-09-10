"""Generated media is a typed result, independent of the model's prose."""
from unittest.mock import AsyncMock, patch

import pytest

from agent.aigc.artifacts import video_artifacts_from_result
from agent.llm.base import LLMResponse, ToolCall
from agent.schemas.aigc import GeneratedVideo, VideoGenerationResponse
from agent.schemas.chat import ChatRequest

URL = '/static/generated/aigc/spark-video-artifact.mp4'


def response():
    return VideoGenerationResponse(id='task-video', prompt='motion',
        videos=[GeneratedVideo(index=0, url=URL)],
        video={'width': 480, 'height': 864, 'duration_seconds': 5.17}, seed_text='123')


def test_video_artifact_preserves_authoritative_url_type_and_metadata():
    artifact, = video_artifacts_from_result('generate_video', response().model_dump())
    assert artifact.type == 'video'
    assert artifact.url == URL
    assert artifact.item_id == URL
    assert artifact.mime_type == 'video/mp4'
    assert artifact.metadata['video']['width'] == 480
    assert artifact.metadata['task_id'] == 'task-video'
    assert artifact.metadata['seed_text'] == '123'
    data = response().model_dump()
    data['videos'] *= 2
    assert len(video_artifacts_from_result('generate_video', data)) == 1


@pytest.mark.parametrize('tool,data', [
    ('search', response().model_dump()), ('generate_video', None),
    ('generate_video', {'videos': None}), ('generate_video', {'videos': [None, {}, {'url': 'javascript:x'}]}),
    ('generate_video', {'videos': [{'url': 'https://external.test/video.mp4'}]}),
    ('generate_video', {'videos': [{'url': '/static/generated/aigc/../video.mp4'}]}),
    ('generate_video', {'videos': [{'url': URL, 'mime_type': 'text/html'}]}),
])
def test_unrelated_or_invalid_results_do_not_become_video_artifacts(tool, data):
    assert video_artifacts_from_result(tool, data) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('reply', ['做好了。', '🎬 **视频已生成**', '不含任何链接的说明'])
async def test_video_tool_result_reaches_chat_and_run_artifacts_independent_of_prose(engine, reply):
    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=[
        LLMResponse(content='', model='test', tool_calls=[ToolCall(
            id='video-artifact-call', name='generate_video', arguments={'prompt': 'motion'})]),
        LLMResponse(content=reply, model='test', tool_calls=[]),
    ])
    with patch.object(engine, '_get_provider', return_value=provider), patch(
        'agent.skills.builtin.generate_video.generate_video', new=AsyncMock(return_value=response())):
        result = await engine.process(ChatRequest(conversation_id='typed-video',
            agent_id='super_chat', message='生成一个视频', memory_enabled=False))
    artifact, = result.artifacts
    assert artifact.url == URL and artifact.type == 'video'
    completed = next(event for event in result.events if event.type == 'run.completed')
    assert completed.payload['artifacts'][0]['url'] == URL


@pytest.mark.asyncio
async def test_failed_video_generation_never_creates_artifact(engine):
    from agent.aigc.spark_client import SparkProviderError
    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=[
        LLMResponse(content='', model='test', tool_calls=[ToolCall(
            id='failed-video-call', name='generate_video', arguments={'prompt': 'motion'})]),
        LLMResponse(content='生成失败。', model='test', tool_calls=[]),
    ])
    with patch.object(engine, '_get_provider', return_value=provider), patch(
        'agent.skills.builtin.generate_video.generate_video',
        new=AsyncMock(side_effect=SparkProviderError('failed', code='generation_failed'))):
        result = await engine.process(ChatRequest(conversation_id='failed-video',
            agent_id='super_chat', message='生成一个视频', memory_enabled=False))
    assert result.artifacts == []
