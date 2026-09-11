import asyncio
import json
import struct
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from agent.aigc.spark_client import SparkProviderError
from agent.aigc.spark_video_client import SparkVideoClient
from agent.aigc.video_service import generate_video
from agent.config import runtime_config
from agent.llm.base import LLMMessage, LLMResponse, ToolCall
from agent.schemas.aigc import GeneratedVideo, VideoGenerationRequest, VideoGenerationResponse
from agent.schemas.chat import ChatRequest
from agent.skills.builtin.generate_video import GenerateVideoSkill


def mp4():
    def box(kind, body):
        return struct.pack('>I', len(body) + 8) + kind + body
    # Container fixture only; codec validation is the Provider's responsibility.
    return box(b'ftyp', b'isom\x00\x00\x02\x00isommp42') + box(b'mdat', b'media') + box(b'moov', b'metadata')


def task(status='succeeded', **changes):
    return dict(id='video-task', type='video', status=status, seed=43, error=None,
                artifacts=[{'id': '0', 'type': 'video', 'media_type': 'video/mp4',
                            'download_url': '/v1/tasks/video-task/artifacts/0'}]) | changes


def make_client(tmp_path, handler, **kwargs):
    return SparkVideoClient('https://spark.test', 'test-secret', output_dir=tmp_path,
                            transport=httpx.MockTransport(handler), poll_interval=0, **kwargs)


def video_response():
    return VideoGenerationResponse(id='video-task', prompt='纸鹤随风飘动，雨声',
        videos=[GeneratedVideo(index=0, url='/static/generated/aigc/spark-video-test.mp4')],
        metadata={'idempotency_key': 'original-key', 'seed': 43})


@pytest.mark.parametrize('frames', [73, 124])
@pytest.mark.asyncio
async def test_video_submit_poll_download(tmp_path, frames):
    requests = []
    states = iter(['queued', 'running', 'recovering', 'succeeded'])
    prompt = '  纸鹤随风飘动，雨声  '
    def handler(request):
        requests.append(request)
        assert request.headers['authorization'] == 'Bearer test-secret'
        if request.method == 'POST':
            assert request.headers['idempotency-key'] == 'original-key'
            assert json.loads(request.content) == {'type': 'video', 'template': 'video.text.v1', 'input': {
                'prompt': prompt, 'width': 864, 'height': 480, 'fps': 24,
                'num_frames': frames, 'seed': None}}
            return httpx.Response(202, json=task('submitting'))
        if '/artifacts/' in request.url.path:
            return httpx.Response(200, content=mp4(), headers={'Content-Type': 'video/mp4'})
        return httpx.Response(200, json=task(next(states)))
    result = await make_client(tmp_path, handler).generate(VideoGenerationRequest(
        prompt=prompt, num_frames=frames, idempotency_key='original-key'))
    assert len(requests) == 6
    assert result.id == 'video-task'
    assert result.video is None  # Pre-0.5 historical tasks remain downloadable.
    assert result.seed_text is None
    assert result.metadata['seed'] == 43
    assert result.metadata['num_frames'] == frames
    assert result.metadata['idempotency_key'] == 'original-key'
    assert result.videos[0].mime_type == 'video/mp4'
    assert (tmp_path / result.videos[0].url.split('/')[-1]).read_bytes() == mp4()
    assert not list(tmp_path.glob('*.part'))


@pytest.mark.parametrize('options', [
    {'prompt': ''}, {'prompt': ' \n '}, {'prompt': 'x' * 4001},
    {'width': 33}, {'height': 720}, {'fps': 121}, {'num_frames': 4},
    *[{field: value} for field in ['width', 'height', 'num_frames']
      for value in ['24', 24.0, True]],
    {'seed': -2}, {'seed': 2**64}, {'negative_prompt': 'blur'},
    {'duration_seconds': 0}, {'image_url': 'https://test/image.png'}, {'first_frame': 'x'},
    {'steps': 10}, {'model': 'h3'}, {'template': 'h3'}, {'idempotency_key': ' '},
])
def test_video_rejects_invalid_parameters(options):
    with pytest.raises(ValidationError):
        VideoGenerationRequest(**({'prompt': 'paper crane'} | options))


@pytest.mark.asyncio
async def test_video_uncertain_submission_reuses_original_key_and_input(tmp_path):
    posts = []
    def handler(request):
        if request.method == 'POST':
            posts.append(request)
            if len(posts) == 1:
                raise httpx.ReadTimeout('lost response')
            if len(posts) == 2:
                return httpx.Response(429, json={'error': {'code': 'provider_busy'}})
            return httpx.Response(202, json=task())
        return httpx.Response(200, content=mp4(), headers={'Content-Type': 'video/mp4'})
    with patch('agent.aigc.spark_client.asyncio.sleep', new=AsyncMock()):
        result = await make_client(tmp_path, handler).generate(VideoGenerationRequest(prompt='paper crane'))
    assert len(posts) == 3
    assert len({r.content for r in posts}) == 1
    assert {r.headers['idempotency-key'] for r in posts} == {result.metadata['idempotency_key']}
    assert json.loads(posts[-1].content)['input']['seed'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [('failed', 'generation_failed'), ('expired', 'artifact_expired')])
async def test_video_terminal_failure_does_not_resubmit(tmp_path, status, code):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=task(status))
    with pytest.raises(SparkProviderError) as error:
        await make_client(tmp_path, handler).generate(VideoGenerationRequest(prompt='crane', idempotency_key='key'))
    assert error.value.context() == {'code': code, 'task_id': 'video-task', 'idempotency_key': 'key'}
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_video_timeout_keeps_resume_information(tmp_path):
    async def handler(request):
        if request.method == 'POST':
            return httpx.Response(202, json=task('running'))
        await asyncio.sleep(1)
    with pytest.raises(SparkProviderError) as error:
        await make_client(tmp_path, handler, timeout=.02).generate(
            VideoGenerationRequest(prompt='crane', idempotency_key='key'))
    assert error.value.context() == {'code': 'wait_timeout', 'task_id': 'video-task', 'idempotency_key': 'key'}
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(401, 'unauthorized'), (409, 'idempotency_conflict'),
                                       (422, 'unsupported_task_type')])
async def test_video_http_errors_do_not_retry_or_expose_credentials(tmp_path, status, code):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={'error': {'code': code, 'message': 'test-secret'}})
    with pytest.raises(SparkProviderError) as error:
        await make_client(tmp_path, handler).generate(VideoGenerationRequest(prompt='crane'))
    assert error.value.code == code
    assert error.value.idempotency_key
    assert 'test-secret' not in str(error.value)
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('artifact', [
    {'download_url': 'https://evil.test/video.mp4'},
    {'download_url': '/v1/tasks/other/artifacts/0'},
    {'download_url': '/v1/tasks/video-task/artifacts/../../other'},
    {'download_url': '/v1/tasks/video-task/artifacts/%2e%2e%2fother'},
    {'download_url': '/v1/tasks/video-task/artifacts/0?key=x'},
    {'media_type': 'image/png'}, {'type': 'image'},
])
async def test_video_rejects_invalid_artifacts_before_download(tmp_path, artifact):
    result = task()
    result['artifacts'][0].update(artifact)
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=result)
    with pytest.raises(SparkProviderError, match='artifact'):
        await make_client(tmp_path, handler).generate(VideoGenerationRequest(prompt='crane'))
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('content,media,status', [
    (b'not a video', 'video/mp4', 200), (mp4()[:-2], 'video/mp4', 200),
    (mp4(), 'text/html', 200), (mp4(), 'video/mp4', 206), (b'', 'video/mp4', 410),
    (b'', 'video/mp4', 302),
])
async def test_video_bad_download_leaves_no_files(tmp_path, content, media, status):
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(202, json=task())
        return httpx.Response(status, content=content, headers={'Content-Type': media, 'Location': 'https://evil.test'})
    with pytest.raises(SparkProviderError):
        await make_client(tmp_path, handler).generate(VideoGenerationRequest(prompt='crane'))
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_video_download_restarts_after_interruption(tmp_path):
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield mp4()[:20]
            raise httpx.ReadError('broken transfer')
    downloads = []
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(202, json=task())
        downloads.append(request)
        assert 'range' not in request.headers
        if len(downloads) == 1:
            return httpx.Response(200, stream=BrokenStream(), headers={'Content-Type': 'video/mp4'})
        return httpx.Response(200, content=mp4(), headers={'Content-Type': 'video/mp4'})
    with patch('agent.aigc.spark_client.asyncio.sleep', new=AsyncMock()):
        result = await make_client(tmp_path, handler).generate(VideoGenerationRequest(prompt='crane'))
    assert len(downloads) == 2
    assert (tmp_path / result.videos[0].url.split('/')[-1]).read_bytes() == mp4()
    assert not list(tmp_path.glob('*.part'))


@pytest.mark.asyncio
async def test_video_service_reuses_spark_config():
    request = VideoGenerationRequest(prompt='crane')
    with patch.dict(runtime_config._data, {'aigc.image_provider': 'minimax',
            'aigc.spark.base_url': 'https://spark.test', 'aigc.spark.api_key': 'test-key'}), patch(
            'agent.aigc.video_service.SparkVideoClient') as client:
        client.return_value.generate = AsyncMock(return_value=video_response())
        result = await generate_video(request)
    client.assert_called_once_with('https://spark.test', 'test-key')
    client.return_value.generate.assert_awaited_once_with(request)
    assert result.videos


@pytest.mark.asyncio
async def test_video_skill_prepares_stable_key_and_reports_failure():
    skill = GenerateVideoSkill()
    args = await skill.prepare_arguments(prompt='crane')
    assert args['idempotency_key']
    assert await skill.prepare_arguments(**args) == args
    failure = SparkProviderError('still running', code='wait_timeout', task_id='video-task',
                                  idempotency_key=args['idempotency_key'])
    with patch('agent.skills.builtin.generate_video.generate_video', new=AsyncMock(side_effect=failure)):
        result = await skill.execute(**args)
    assert not result.success
    assert result.error_code == 'wait_timeout'
    assert result.data['idempotency_key'] == args['idempotency_key']
    assert result.data['task_id'] == 'video-task'
    with patch('agent.skills.builtin.generate_video.generate_video', new=AsyncMock()) as generate:
        result = await skill.execute(prompt='crane', negative_prompt='blur')
    assert result.error_code == 'invalid_request'
    generate.assert_not_called()


def test_video_tool_routing_and_disable(engine):
    for query in ['生成纸鹤的视频', 'make a video', '你好']:
        request = ChatRequest(conversation_id='video', agent_id='super_chat', message=query)
        _, tools, _ = engine._routed_tool_definitions_for_request(request, agent_id='super_chat')
        assert 'generate_video' in {tool.name for tool in tools}
        _, tools, _ = engine._routed_tool_definitions_for_request(
            request, agent_id='super_chat', disabled_tools={'generate_video'})
        assert 'generate_video' not in {tool.name for tool in tools}
    assert 'generate_video' not in {tool.name for tool in engine._tool_definitions_for_agent(agent_id='general_assistant')}


@pytest.mark.asyncio
@pytest.mark.parametrize('options', [
    {'num_frames': 73},
    {'duration_seconds': 5, 'fps': 29.97, 'width': 480, 'height': 864, 'seed': str(2**64-1)},
])
async def test_super_chat_video_tool_preserves_result_link_and_trace(engine, options):
    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=[
        LLMResponse(content='', model='test', tool_calls=[ToolCall(id='video-call', name='generate_video',
            arguments={'prompt': '纸鹤随风飘动，雨声', **options})]),
        LLMResponse(content='视频已生成。', model='test', tool_calls=[]),
    ])
    with patch.object(engine, '_get_provider', return_value=provider), patch(
            'agent.skills.builtin.generate_video.generate_video', new=AsyncMock(return_value=video_response())) as generate:
        result = await engine.process(ChatRequest(conversation_id='video-tool', agent_id='super_chat',
            message='生成一个纸鹤随风飘动的视频', memory_enabled=False))
    request = generate.await_args.args[0]
    for field, value in options.items():
        assert getattr(request, field) == value
    if 'duration_seconds' in options:
        assert request.num_frames is None
    assert request.idempotency_key
    assert '[AI 生视频 1](/static/generated/aigc/spark-video-test.mp4)' in result.response
    assert 'generate_video' in result.skills_used
    assert any(event.type == 'tool.governance.allowed' for event in result.events)
    assert any(event.type == 'tool.completed' and event.payload['name'] == 'generate_video' for event in result.events)
    assert 'generate_video' in provider.chat.await_args_list[0].args[0][0].content
    assert 'seed_text' in provider.chat.await_args_list[0].args[0][0].content
    assert '固定 864×480' not in provider.chat.await_args_list[0].args[0][0].content
    assert '不能交换' in provider.chat.await_args_list[0].args[0][0].content
    assert '不能声称横屏等同竖屏' in provider.chat.await_args_list[0].args[0][0].content


@pytest.mark.parametrize('tool_name,success', [('search', True), ('generate_video', False)])
def test_video_link_restore_ignores_unrelated_or_failed_tools(engine, tool_name, success):
    messages = [LLMMessage(role='assistant', content='', tool_calls=[{'id': 'call', 'name': tool_name, 'arguments': {}}]),
                LLMMessage(role='tool', tool_call_id='call', content=json.dumps({
                    'success': success, 'data': video_response().model_dump()}))]
    assert engine._restore_generated_video_links('未生成', messages) == '未生成'


def test_video_retry_context_survives_memory_compaction(engine):
    result = json.loads(engine._compact_tool_result_for_memory(json.dumps({'success': False, 'data': {
        'code': 'wait_timeout', 'task_id': 'video-task', 'idempotency_key': 'original-key'}})))
    assert result['data']['idempotency_key'] == 'original-key'
    assert result['data']['task_id'] == 'video-task'


@pytest.mark.parametrize('query', ['帮我生成一只小猫的视频', 'draw a cat video'])
def test_video_request_does_not_force_image_generation(query):
    from agent.skills.router import explicit_image_generation_request
    assert not explicit_image_generation_request(query)


@pytest.mark.asyncio
async def test_video_size_limit_applies_to_stream_without_content_length(tmp_path):
    class VideoStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield mp4()
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(202, json=task())
        return httpx.Response(200, stream=VideoStream(), headers={'Content-Type': 'video/mp4'})
    with patch('agent.aigc.spark_video_client.MAX_VIDEO_BYTES', 16), pytest.raises(SparkProviderError):
        await make_client(tmp_path, handler).generate(VideoGenerationRequest(prompt='crane'))
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_video_cancelled_download_removes_partial_file(tmp_path):
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'x' * (64 * 1024)
            assert list(tmp_path.glob('*.part'))
            await asyncio.sleep(1)
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(202, json=task())
        return httpx.Response(200, stream=SlowStream(), headers={'Content-Type': 'video/mp4'})
    with pytest.raises(SparkProviderError) as error:
        await make_client(tmp_path, handler, timeout=.02).generate(VideoGenerationRequest(prompt='crane'))
    assert error.value.code == 'wait_timeout'
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'id': 'another-task'}, {'type': 'image'}, {'status': 'unknown'}])
async def test_video_rejects_mismatched_poll_response(tmp_path, changes):
    def handler(request):
        return httpx.Response(200, json=task('queued') if request.method == 'POST' else task(**changes))
    with pytest.raises(SparkProviderError) as error:
        await make_client(tmp_path, handler).generate(VideoGenerationRequest(prompt='crane'))
    assert error.value.code == 'invalid_response'
    assert error.value.task_id == 'video-task'


@pytest.mark.parametrize('reply', [
    '视频已生成。', '[视频](attachment://spark-video-test.mp4)',
    '![视频](/static/generated/aigc/spark-video-test.mp4)',
    '[小兔子](https://mini.amini.net/static/generated/aigc/spark-video-test.mp4)',
    '[小兔子](https://mini.amini.net/static/generated/aigc/spark-video-test.mp4?download=1#t=0)',
    '[小兔子](https://mini.amini.net/static/generated/aigc/spark-video-test.mp4)\n\n'
    '[AI 生视频 1](/static/generated/aigc/spark-video-test.mp4)',
])
def test_video_links_restore_actual_url_without_image_syntax(engine, reply):
    messages = [LLMMessage(role='assistant', content='', tool_calls=[{'id': 'call', 'name': 'generate_video', 'arguments': {}}]),
                LLMMessage(role='tool', tool_call_id='call', content=json.dumps({
                    'success': True, 'data': video_response().model_dump()}))]
    result = engine._restore_generated_video_links(reply, messages)
    assert result.count('/static/generated/aigc/spark-video-test.mp4') == 1
    assert '![' not in result
    assert 'attachment://' not in result
    assert 'mini.amini.net' not in result


def test_video_link_restore_preserves_unrelated_urls_and_distinct_outputs(engine):
    urls = ['/static/generated/aigc/spark-video-test.mp4', '/static/generated/aigc/spark-video-other.mp4']
    messages = [LLMMessage(role='assistant', content='', tool_calls=[{'id': 'call', 'name': 'generate_video'}]),
                LLMMessage(role='tool', tool_call_id='call', content=json.dumps({
                    'success': True, 'data': {'videos': [{'url': url} for url in urls]}}))]
    unrelated = ['https://cdn.test/other/spark-video-test.mp4',
                 'https://cdn.test/static/generated/aigc/unknown.mp4', 'https://[invalid/a.mp4']
    reply = '\n\n'.join(f'[参考]({url})' for url in unrelated)
    result = engine._restore_generated_video_links(reply, messages)
    for url in urls + unrelated:
        assert result.count(f']({url})') == 1


@pytest.mark.asyncio
async def test_video_deny_policy_prevents_generation(engine):
    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=[
        LLMResponse(content='', model='test', tool_calls=[ToolCall(id='video-denied', name='generate_video',
            arguments={'prompt': 'paper crane'})]),
        LLMResponse(content='视频工具被禁用。', model='test', tool_calls=[]),
    ])
    with patch.object(engine, '_get_provider', return_value=provider), patch(
            'agent.skills.builtin.generate_video.generate_video', new=AsyncMock()) as generate:
        result = await engine.process(ChatRequest(conversation_id='video-denied', agent_id='super_chat',
            message='生成一个纸鹤的视频', memory_enabled=False, tool_policies={'generate_video': 'deny'}))
    generate.assert_not_called()
    assert '/static/generated/' not in result.response


@pytest.mark.asyncio
async def test_shared_task_client_reports_expired_image(tmp_path):
    from agent.aigc.spark_client import SparkImageClient
    from agent.schemas.aigc import ImageGenerationRequest
    client = SparkImageClient('https://spark.test', 'test-key', output_dir=tmp_path,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=task('expired', type='image'))))
    with pytest.raises(SparkProviderError) as error:
        await client.generate(ImageGenerationRequest(prompt='crane'))
    assert error.value.code == 'artifact_expired'
    assert error.value.idempotency_key


@pytest.mark.parametrize('options,frames', [
    ({}, 124), ({'num_frames': 120}, 124), ({'num_frames': 5}, 5),
    ({'duration_seconds': 5}, 124), ({'duration_seconds': 10.0}, 243),
    ({'duration_seconds': 15, 'width': 1344, 'height': 768}, 362),
    ({'duration_seconds': .01, 'width': 32, 'height': 32}, 5),
    ({'duration_seconds': 3592 / 24, 'width': 320, 'height': 320}, 3592),
    ({'num_frames': 889}, 889), ({'num_frames': 3592, 'width': 320, 'height': 320}, 3592),
    ({'num_frames': 5, 'width': 4096, 'height': 32}, 5),
    ({'num_frames': None, 'duration_seconds': 5}, 124),
    ({'duration_seconds': None, 'num_frames': 120}, 124),
])
def test_video_v05_frame_alignment_and_resource_boundaries(options, frames):
    request = VideoGenerationRequest(prompt='crane', **options)
    assert request.resolved_frames() == frames
    payload = SparkVideoClient.payload(request)['input']
    if options.get('duration_seconds') is not None:
        assert payload['duration_seconds'] == options['duration_seconds']
        assert 'num_frames' not in payload
    else:
        assert payload['num_frames'] == options.get('num_frames', 124)
        assert 'duration_seconds' not in payload


@pytest.mark.parametrize('options', [
    {'width': 0}, {'width': 4097}, {'width': 1376, 'height': 768},
    {'width': 1344, 'height': 768, 'num_frames': 363},
    {'width': 1344, 'height': 768, 'duration_seconds': 15.1},
    {'num_frames': 890}, {'num_frames': 3593, 'width': 32, 'height': 32},
    {'num_frames': None}, {'duration_seconds': None}, {'num_frames': None, 'duration_seconds': None},
    {'num_frames': 124, 'duration_seconds': 5},
    {'duration_seconds': 150}, {'duration_seconds': -1}, {'duration_seconds': '5'},
    {'duration_seconds': True}, {'duration_seconds': float('nan')}, {'duration_seconds': float('inf')},
    {'fps': 0}, {'fps': '24'}, {'fps': True}, {'fps': 29.97001}, {'fps': float('nan')}, {'fps': float('inf')},
    {'seed': str(2**64)}, {'seed': '-1'}, {'seed': '1e5'}, {'seed': ' 43'},
    {'seed': True}, {'seed': 43.0}, {'seed': '9' * 1000}, {'seed': '４３'},
])
def test_video_v05_invalid_requests_rejected_before_submission(options):
    with pytest.raises(ValidationError):
        VideoGenerationRequest(prompt='crane', **options)


@pytest.mark.parametrize('seed', [0, 2**32, 2**64-1, str(2**64-1), '000043', None, -1])
@pytest.mark.asyncio
async def test_video_v05_seed_and_duration_survive_argument_preparation(seed):
    skill = GenerateVideoSkill()
    args = await skill.prepare_arguments(prompt='crane', duration_seconds=5, fps=29.97, seed=seed)
    assert 'num_frames' not in args
    assert args['duration_seconds'] == 5
    assert args.get('seed') == (None if seed is None or seed == -1 else str(int(seed)))
    assert await skill.prepare_arguments(**args) == args
    payload = SparkVideoClient.payload(VideoGenerationRequest(**args))['input']
    assert payload['seed'] == args.get('seed')
    assert 'num_frames' not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize('fps,output_frames,duration', [(24,124,124/24), (30,155,155/30),
    (29.97,155,155/29.97), (23.976,124,124/23.976), (1,6,6.0), (120,620,620/120)])
async def test_video_v05_preserves_execution_metadata_and_exact_seed(tmp_path, fps, output_frames, duration):
    video = {'width': 480, 'height': 864, 'requested_num_frames': None, 'requested_duration_seconds': 5.0,
             'num_frames': 124, 'native_fps': 24, 'native_duration_seconds': 124/24,
             'fps': fps, 'output_num_frames': output_frames, 'duration_seconds': duration, 'fps_mode': 'resample'}
    posts = []
    def handler(request):
        if request.method == 'POST':
            posts.append(request)
            if len(posts) == 1:
                raise httpx.ReadTimeout('lost create response')
            body = json.loads(request.content)['input']
            assert body['seed'] == str(2**64-1)
            assert body['duration_seconds'] == 5
            assert body['fps'] == fps
            assert 'num_frames' not in body
            return httpx.Response(202, json=task(seed=2**64-1, seed_text=str(2**64-1), video=video))
        return httpx.Response(200, content=mp4(), headers={'Content-Type': 'video/mp4'})
    with patch('agent.aigc.spark_client.asyncio.sleep', new=AsyncMock()):
        result = await make_client(tmp_path, handler).generate(VideoGenerationRequest(prompt='crane',
            width=480, height=864, duration_seconds=5, fps=fps, seed=str(2**64-1), idempotency_key='stable'))
    assert len({request.content for request in posts}) == 1
    assert {request.headers['idempotency-key'] for request in posts} == {'stable'}
    assert result.seed_text == str(2**64-1)
    assert result.video == video
    assert result.metadata['num_frames'] == 124
    assert result.metadata['output_num_frames'] == output_frames
    assert result.metadata['duration_seconds'] == duration
    assert result.metadata['seed_text'] == str(2**64-1)


def test_video_tool_schema_exposes_v05_options():
    properties = GenerateVideoSkill().to_tool_definition()['parameters']['properties']
    assert properties['width']['minimum'] == 32
    assert properties['width']['maximum'] == 4096
    assert properties['width']['multipleOf'] == 32
    assert properties['num_frames']['maximum'] == 3592
    assert properties['fps']['type'] == 'number'
    assert properties['fps']['maximum'] == 120
    assert properties['duration_seconds']['exclusiveMinimum'] == 0
    assert {item['type'] for item in properties['seed']['anyOf']} >= {'integer', 'string'}
    assert 'enum' not in properties['num_frames']
    assert 'enum' not in properties['fps']


@pytest.mark.asyncio
async def test_video_v05_prepared_invalid_input_never_calls_provider():
    with patch('agent.skills.builtin.generate_video.generate_video', new=AsyncMock()) as generate:
        result = await GenerateVideoSkill().execute(prompt='crane', width=1344, height=768, num_frames=363)
    assert result.error_code == 'invalid_request'
    generate.assert_not_called()


def test_video_v05_execution_metadata_survives_memory_compaction(engine):
    data = {'seed_text': str(2**64-1), 'video': {'num_frames': 124, 'output_num_frames': 155,
            'fps': 29.97, 'duration_seconds': 155/29.97}}
    result = json.loads(engine._compact_tool_result_for_memory(json.dumps({'success': True, 'data': data})))
    assert result['data'] == data


def test_video_v05_time_input_remains_distinct_for_idempotency():
    frames = SparkVideoClient.payload(VideoGenerationRequest(prompt='crane', num_frames=120))
    duration = SparkVideoClient.payload(VideoGenerationRequest(prompt='crane', duration_seconds=5))
    assert frames != duration
    assert frames['input']['num_frames'] == 120
    assert duration['input']['duration_seconds'] == 5
