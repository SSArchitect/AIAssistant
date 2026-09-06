import asyncio
import base64
import json
import struct
import zlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from agent.aigc.image_service import generate_image
from agent.aigc.spark_client import SparkImageClient, SparkProviderError
from agent.config import RuntimeConfig, runtime_config
from agent.schemas.aigc import GeneratedImage, ImageGenerationRequest, ImageGenerationResponse
from agent.skills.builtin.generate_image import GenerateImageSkill
from agent.skills.registry import SkillRegistry


def png(width=1024, height=1024):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0' * ((width + 1) * height))) + chunk(b'IEND', b''))


def task(status='succeeded', **extra):
    return dict(id='task-123', status=status, seed=42, error=None,
                artifacts=[{'id': 'opaque-artifact', 'media_type': 'image/png',
                            'download_url': '/v1/tasks/task-123/artifacts/opaque-artifact'}], **extra)


def make_client(tmp_path, handler, **kwargs):
    return SparkImageClient('https://spark.test', 'secret-test-key', output_dir=tmp_path,
                            transport=httpx.MockTransport(handler), poll_interval=0, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('response_format', ['url', 'base64'])
async def test_spark_submit_poll_authenticated_download(tmp_path, response_format):
    requests = []
    statuses = iter(['running', 'recovering', 'succeeded'])
    def handler(request):
        requests.append(request)
        assert request.headers['authorization'] == 'Bearer secret-test-key'
        if request.method == 'POST':
            assert request.headers['idempotency-key'] == 'stable-key'
            assert json.loads(request.content) == {'type': 'image', 'input': {
                'prompt': 'robot', 'negative_prompt': 'blur', 'width': 1024, 'height': 1024, 'seed': 42}}
            return httpx.Response(202, json=task('queued'))
        if '/artifacts/' in request.url.path:
            return httpx.Response(200, content=png(), headers={'Content-Type': 'image/png'})
        return httpx.Response(200, json=task(next(statuses)))
    result = await make_client(tmp_path, handler).generate(ImageGenerationRequest(
        prompt='robot', negative_prompt='blur', seed=42, idempotency_key='stable-key', response_format=response_format))
    assert result.provider == 'spark'
    assert result.id == 'task-123'
    assert result.metadata['seed'] == 42
    assert len(requests) == 5
    if response_format == 'url':
        assert result.images[0].url.startswith('/static/generated/aigc/spark-')
        assert (tmp_path / result.images[0].url.split('/')[-1]).read_bytes() == png()
    else:
        assert base64.b64decode(result.images[0].base64) == png()
        assert list(tmp_path.iterdir()) == []
    assert not list(tmp_path.glob('*.part'))


@pytest.mark.asyncio
async def test_create_retries_preserve_key_and_original_random_seed(tmp_path):
    seen = []
    def handler(request):
        if request.method == 'POST':
            seen.append(request)
            if len(seen) == 1:
                raise httpx.ReadTimeout('uncertain submission')
            if len(seen) == 2:
                return httpx.Response(503, text='proxy error')
            return httpx.Response(202, json=task())
        return httpx.Response(200, content=png(), headers={'Content-Type': 'image/png'})
    with patch('agent.aigc.spark_client.asyncio.sleep', new=AsyncMock()):
        result = await make_client(tmp_path, handler).generate(ImageGenerationRequest(prompt='robot'))
    assert len(seen) == 3
    assert len({r.headers['idempotency-key'] for r in seen}) == 1
    assert len({r.content for r in seen}) == 1
    assert json.loads(seen[0].content)['input']['seed'] is None
    assert result.metadata['idempotency_key'] == seen[0].headers['idempotency-key']


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(401,'unauthorized'), (409,'idempotency_conflict'), (422,'invalid_request')])
async def test_nonretryable_http_errors(tmp_path, status, code):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={'error': {'code': code, 'message': 'secret-test-key'}})
    with pytest.raises(SparkProviderError) as error:
        await make_client(tmp_path, handler).generate(ImageGenerationRequest(prompt='robot', idempotency_key='original'))
    assert len(requests) == 1
    assert error.value.code == code
    assert error.value.idempotency_key == 'original'
    assert 'secret-test-key' not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, {}, {'id':'x','status':'unknown'}])
async def test_bad_json_or_task(tmp_path, body):
    def handler(request):
        return httpx.Response(202, json=body) if body is not None else httpx.Response(202, text='<html>bad proxy</html>')
    with pytest.raises(SparkProviderError, match='invalid task'):
        await make_client(tmp_path, handler).generate(ImageGenerationRequest(prompt='robot'))


@pytest.mark.asyncio
async def test_failed_task_is_not_recreated(tmp_path):
    seen = []
    def handler(request):
        seen.append(request)
        body = task('failed')
        body['error'] = {'code':'generation_failed', 'message':'backend details'}
        return httpx.Response(202, json=body)
    with pytest.raises(SparkProviderError) as error:
        await make_client(tmp_path, handler).generate(ImageGenerationRequest(prompt='robot'))
    assert error.value.task_id == 'task-123'
    assert error.value.code == 'generation_failed'
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_deadline_keeps_task_id_and_key(tmp_path):
    async def handler(request):
        if request.method == 'GET':
            await asyncio.sleep(10)
        return httpx.Response(202, json=task('recovering'))
    with pytest.raises(SparkProviderError) as error:
        await make_client(tmp_path, handler, timeout=0.03).generate(
            ImageGenerationRequest(prompt='robot', idempotency_key='retry-this'))
    assert error.value.context() == {'code':'wait_timeout','task_id':'task-123','idempotency_key':'retry-this'}


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['https://evil.test/image', '//evil.test/image', '/v1/tasks/other/artifacts/0'])
async def test_download_never_sends_key_to_another_origin_or_task(tmp_path, path):
    calls = []
    def handler(request):
        calls.append(request)
        body = task()
        body['artifacts'][0]['download_url'] = path
        return httpx.Response(202, json=body)
    with pytest.raises(SparkProviderError, match='invalid artifact'):
        await make_client(tmp_path, handler).generate(ImageGenerationRequest(prompt='robot'))
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('status,content_type,content', [(410,'application/json',b'{}'),(200,'text/html',b'bad'),(200,'image/png',b'broken')])
async def test_failed_download_leaves_no_output(tmp_path, status, content_type, content):
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(202, json=task())
        return httpx.Response(status, content=content, headers={'Content-Type':content_type})
    with pytest.raises(SparkProviderError):
        await make_client(tmp_path, handler).generate(ImageGenerationRequest(prompt='robot'))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('options', [{'width':4096,'height':4096}, {'width':1032,'height':1024}, {'n':2},
                                   {'model':'custom'}, {'subject_reference':[{'image':'example'}]}, {'style':{'x':1}}, {'aigc_watermark':True}])
def test_spark_rejects_unsupported_parameters(options):
    with pytest.raises(ValueError):
        SparkImageClient.payload(ImageGenerationRequest(prompt='robot', **options))


@pytest.mark.parametrize('options', [{'seed':True}, {'seed':'42'}, {'seed':1.5}, {'seed':-1}, {'seed':4294967296},
                                   {'prompt':' '}, {'idempotency_key':' '}, {'width':1024.0,'height':1024}])
def test_invalid_input_rejected(options):
    with pytest.raises(ValidationError):
        ImageGenerationRequest(**({'prompt':'robot'} | options))


def test_runtime_media_configuration(monkeypatch):
    from agent.config import Settings
    monkeypatch.setenv('MEDIA_BASE_URL', 'https://spark.test')
    monkeypatch.setenv('MEDIA_API_KEY', 'test-key')
    monkeypatch.setenv('IMAGE_PROVIDER', 'spark')
    with patch('agent.config.settings', Settings(_env_file=None)):
        config = RuntimeConfig()
    assert config.get('aigc.spark.base_url') == 'https://spark.test'
    assert config.get('aigc.spark.api_key') == 'test-key'
    assert config.get('aigc.image_provider') == 'spark'


@pytest.mark.asyncio
async def test_service_selects_spark_and_passes_request(tmp_path):
    request = ImageGenerationRequest(prompt='robot', provider='spark', negative_prompt='blur')
    with patch.dict(runtime_config._data, {'aigc.spark.base_url':'https://spark.test','aigc.spark.api_key':'test'}), patch(
            'agent.aigc.image_service.SparkImageClient.generate', new=AsyncMock(return_value='result')) as generate:
        assert await generate_image(request) == 'result'
        generate.assert_awaited_once_with(request)


@pytest.mark.asyncio
@pytest.mark.parametrize('options', [{'prompt':'x'*1501}, {'negative_prompt':'blur'}, {'idempotency_key':'key'}])
async def test_minimax_does_not_silently_drop_new_options(options):
    with pytest.raises(ValueError):
        await generate_image(ImageGenerationRequest(**({'prompt':'robot','provider':'minimax'} | options)))


@pytest.mark.asyncio
async def test_only_workflow_tool_is_discovered_and_internal_adapter_still_works():
    registry = SkillRegistry()
    registry.auto_discover('agent.skills.builtin')
    assert registry.get('generate_image') is None
    public = registry.get('image_generation_v1')
    assert public is not None
    assert {'provider','width','height','seed'} <= {p.name for p in public.metadata().parameters}
    skill = GenerateImageSkill()
    prepared = await skill.prepare_arguments(prompt='robot', provider='spark')
    assert prepared['idempotency_key']
    assert (await skill.prepare_arguments(**prepared)) == prepared
    response = ImageGenerationResponse(provider='spark', model='z-image-base', prompt='robot', aspect_ratio='1:1',
                response_format='url', images=[GeneratedImage(index=0, url='/static/generated/aigc/test.png')])
    with patch('agent.skills.builtin.generate_image.generate_image', new=AsyncMock(return_value=response)):
        result = await skill.execute(**prepared)
    assert result.success
    assert result.data['provider'] == 'spark'
    assert result.display_text == '![AI 生图 1](/static/generated/aigc/test.png)'
    assert (await skill.execute(prompt='robot', bogus=True)).success is False


@pytest.mark.asyncio
async def test_tool_timeout_returns_resumption_context():
    failure = SparkProviderError('still running', code='wait_timeout', task_id='t', idempotency_key='key')
    with patch('agent.skills.builtin.generate_image.generate_image', new=AsyncMock(side_effect=failure)):
        result = await GenerateImageSkill().execute(prompt='robot', provider='spark')
    assert not result.success
    assert result.data['task_id'] == 't'
    assert result.data['idempotency_key'] == 'key'
    assert not result.retryable  # Caller must deliberately reuse the key, not blindly start another generation.


@pytest.mark.asyncio
async def test_poll_transient_failure_does_not_resubmit(tmp_path):
    posts = 0
    polls = 0
    def handler(request):
        nonlocal posts, polls
        if request.method == 'POST':
            posts += 1
            return httpx.Response(202, json=task('queued'))
        if '/artifacts/' in request.url.path:
            return httpx.Response(200, content=png(), headers={'Content-Type':'image/png'})
        polls += 1
        if polls == 1:
            return httpx.Response(502, text='proxy unavailable')
        return httpx.Response(200, json=task())
    with patch('agent.aigc.spark_client.asyncio.sleep', new=AsyncMock()):
        await make_client(tmp_path, handler).generate(ImageGenerationRequest(prompt='robot'))
    assert posts == 1
    assert polls == 2


@pytest.mark.asyncio
async def test_broken_download_restarts_without_partial_file(tmp_path):
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield png()[:30]
            raise httpx.ReadError('interrupted')
    downloads = 0
    def handler(request):
        nonlocal downloads
        if request.method == 'POST':
            return httpx.Response(202, json=task())
        downloads += 1
        if downloads == 1:
            return httpx.Response(200, stream=BrokenStream(), headers={'Content-Type':'image/png'})
        return httpx.Response(200, content=png(), headers={'Content-Type':'image/png'})
    with patch('agent.aigc.spark_client.asyncio.sleep', new=AsyncMock()):
        result = await make_client(tmp_path, handler).generate(ImageGenerationRequest(prompt='robot'))
    assert downloads == 2
    assert (tmp_path / result.images[0].url.split('/')[-1]).read_bytes() == png()
    assert not list(tmp_path.glob('*.part'))


def test_spark_failure_message_identifies_provider(engine):
    from agent.schemas.chat import ChatRequest
    error = SparkProviderError('Spark HTTP 401 (unauthorized)', code='unauthorized')
    message = engine._aigc_image_error_message(error, request=ChatRequest(conversation_id='test', message='robot'), review={})
    assert 'Spark' in message
    assert 'MiniMax' not in message


@pytest.mark.asyncio
@pytest.mark.parametrize('width,height', [(512,512),(832,1216),(1536,1024),(1920,1088),(2048,2048),(4096,1024),(256,1024)])
async def test_spark_custom_dimensions_are_sent_downloaded_and_reported(tmp_path, width, height):
    def handler(request):
        if request.method == 'POST':
            inputs = json.loads(request.content)['input']
            assert (inputs['width'], inputs['height']) == (width, height)
            return httpx.Response(202, json=task())
        return httpx.Response(200, content=png(width,height), headers={'Content-Type':'image/png'})
    result = await make_client(tmp_path, handler).generate(ImageGenerationRequest(prompt='robot', width=width,height=height))
    assert result.metadata['width'] == width
    assert result.metadata['height'] == height
    numerator, denominator = map(int, result.aspect_ratio.split(':'))
    assert numerator * height == denominator * width
    assert (tmp_path / result.images[0].url.split('/')[-1]).read_bytes() == png(width,height)


@pytest.mark.parametrize('width,height', [(256,256),(4096,4096),(1920,1080),(1032,1024),(240,2048),(4112,1024)])
def test_spark_dimension_limits_reject_without_resizing(width, height):
    with pytest.raises(ValueError):
        SparkImageClient.payload(ImageGenerationRequest(prompt='robot',width=width,height=height))


@pytest.mark.asyncio
async def test_custom_download_must_match_requested_dimensions(tmp_path):
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(202, json=task())
        return httpx.Response(200, content=png(), headers={'Content-Type':'image/png'})
    with pytest.raises(SparkProviderError, match='invalid'):
        await make_client(tmp_path, handler).generate(ImageGenerationRequest(prompt='robot',width=2048,height=2048))
    assert list(tmp_path.iterdir()) == []


def test_spark_ratio_uses_valid_preset_and_explicit_dimensions_take_precedence():
    payload = SparkImageClient.payload(ImageGenerationRequest(prompt='robot',aspect_ratio='16:9'))
    assert payload['input']['width'] * 9 == payload['input']['height'] * 16
    explicit = SparkImageClient.payload(ImageGenerationRequest(prompt='robot',width=832,height=1216))
    assert (explicit['input']['width'],explicit['input']['height']) == (832,1216)


@pytest.mark.asyncio
@pytest.mark.parametrize('default,override,expected', [('minimax',None,'minimax'),('spark',None,'spark'),
    ('minimax','spark','spark'),('spark','minimax','minimax')])
async def test_image_provider_routing_independent_of_chat_provider(default, override, expected):
    from agent.aigc.minimax_client import MiniMaxAIGCClient
    minimax = AsyncMock()
    minimax.image_model = 'image-01'
    minimax.generate_image.return_value = {'data':{'image_urls':['https://minimax.test/image.png']}}
    spark_response = ImageGenerationResponse(provider='spark',model='z-image-base',prompt='robot',aspect_ratio='1:1',
        response_format='url',images=[GeneratedImage(index=0,url='/static/generated/aigc/spark.png')])
    with patch.dict(runtime_config._data, {'llm.default_provider':'claude','aigc.image_provider':default,
        'aigc.spark.base_url':'https://spark.test','aigc.spark.api_key':'test'}), patch.object(
        MiniMaxAIGCClient,'from_runtime_config',return_value=minimax), patch.object(
        SparkImageClient,'generate',new=AsyncMock(return_value=spark_response)) as spark:
        response = await generate_image(ImageGenerationRequest(prompt='robot',provider=override))
    assert response.provider == expected
    assert spark.await_count == int(expected == 'spark')
    assert minimax.generate_image.await_count == int(expected == 'minimax')


@pytest.mark.asyncio
@pytest.mark.parametrize('width,height', [(256,1024),(4096,1024)])
async def test_spark_dimension_extension_does_not_relax_minimax(width,height):
    with pytest.raises(ValueError,match='MiniMax'):
        await generate_image(ImageGenerationRequest(provider='minimax',prompt='robot',width=width,height=height))


@pytest.mark.parametrize('width,height', [(2048,2048),(4096,1024),(256,1024)])
def test_workflow_review_preserves_explicit_sizes(engine,width,height):
    with patch.dict(runtime_config._data, {'aigc.image_provider':'spark'}):
        review = engine._coerce_aigc_review({'should_generate':True,'final_prompt':'robot','width':width,'height':height},
                                           fallback_prompt='robot')
    assert review['should_generate']
    assert (review['width'],review['height']) == (width,height)


@pytest.mark.parametrize('width,height', [(4096,4096),(1920,1080),('2048',2048),(2048,None)])
def test_workflow_invalid_dimensions_do_not_silently_fall_back(engine,width,height):
    with patch.dict(runtime_config._data, {'aigc.image_provider':'spark'}):
        review = engine._coerce_aigc_review({'should_generate':True,'final_prompt':'robot','width':width,'height':height},
                                           fallback_prompt='robot')
    assert not review['should_generate']
    assert '尺寸' in review['clarifying_question']


@pytest.mark.asyncio
async def test_tool_preserves_custom_dimensions_and_exposes_ratio():
    skill = GenerateImageSkill()
    arguments = await skill.prepare_arguments(prompt='robot',provider='spark',width=2048,height=2048)
    assert (arguments['width'], arguments['height']) == (2048,2048)
    schema = skill.to_tool_definition()['parameters']['properties']
    assert '16:9' in schema['aspect_ratio']['enum']
    assert '4096' in schema['width']['description']


def test_missing_spark_url_is_reported_as_missing_configuration():
    with pytest.raises(ValueError,match='base URL not configured'):
        SparkImageClient('', '')
