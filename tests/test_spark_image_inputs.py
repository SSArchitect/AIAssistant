import base64
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from agent.aigc.image_inputs import attachment_image, decode_image_data_url, spark_image_options
from agent.aigc.spark_client import SparkImageClient, SparkProviderError
from agent.aigc.spark_video_client import SparkVideoClient
from agent.schemas.aigc import ImageGenerationRequest, VideoGenerationRequest
from agent.schemas.chat import ChatAttachment, ChatRequest
from agent.skills.builtin.generate_image import GenerateImageSkill
from agent.skills.builtin.generate_video import GenerateVideoSkill
from tests.test_spark_image import png, task as image_task
from tests.test_spark_video import mp4, task as video_task, video_response

ASSET = 'de305d54-75b4-431b-adb2-eb6b9e546014'
DATA = 'data:image/png;base64,' + base64.b64encode(png(320,240)).decode()


def attachment():
    return ChatAttachment(name='source.png',kind='image',type='image/png',data_url=DATA)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['image','video'])
async def test_upload_then_task_download_with_stable_retries(tmp_path, kind):
    uploads, tasks = [], []
    def handler(request):
        assert request.headers['authorization'] == 'Bearer secret'
        if request.url.path == '/v1/assets':
            uploads.append(request)
            assert request.content == png(320,240)
            if len(uploads) == 1:
                raise httpx.ReadTimeout('lost upload response')
            return httpx.Response(201,json={'id':ASSET,'status':'ready'})
        if request.method == 'POST':
            tasks.append(request)
            payload = json.loads(request.content)
            assert payload['mode'] == ('image_to_image' if kind == 'image' else 'image_to_video')
            assert payload['input']['image_asset_id' if kind == 'image' else 'first_frame_asset_id'] == ASSET
            assert payload['input']['image_fit'] == 'center_crop'
            assert 'data_url' not in request.content.decode()
            if len(tasks) == 1:
                return httpx.Response(503)
            return httpx.Response(202,json=(image_task() if kind == 'image' else video_task()))
        return httpx.Response(200,content=png() if kind == 'image' else mp4(),
                              headers={'Content-Type':'image/png' if kind == 'image' else 'video/mp4'})
    options = dict(base_url='https://spark.test',api_key='secret',output_dir=tmp_path,transport=httpx.MockTransport(handler))
    client = SparkImageClient(**options) if kind == 'image' else SparkVideoClient(**options)
    request = ImageGenerationRequest(prompt='redraw',image_data_url=DATA,idempotency_key='stable') if kind == 'image' else VideoGenerationRequest(prompt='animate',first_frame_data_url=DATA,idempotency_key='stable')
    with patch('agent.aigc.spark_client.asyncio.sleep',new=AsyncMock()):
        result = await client.generate(request)
    assert len({r.headers['idempotency-key'] for r in uploads}) == 1
    assert len({r.content for r in uploads}) == 1
    assert len({r.content for r in tasks}) == 1
    assert {r.headers['idempotency-key'] for r in tasks} == {'stable'}
    assert result.metadata['mode'] == request.mode


@pytest.mark.asyncio
async def test_expired_upload_replay_can_resume_existing_task(tmp_path):
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path == '/v1/assets':
            return httpx.Response(201,json={'id':ASSET,'status':'expired'})
        if request.method == 'POST':
            return httpx.Response(202,json=image_task())
        return httpx.Response(200,content=png(),headers={'Content-Type':'image/png'})
    await SparkImageClient('https://spark.test','secret',output_dir=tmp_path,transport=httpx.MockTransport(handler)).generate(
        ImageGenerationRequest(prompt='redraw',image_data_url=DATA,idempotency_key='stable'))
    assert seen[:2] == ['/v1/assets','/v1/tasks']


@pytest.mark.asyncio
async def test_upload_failure_retains_task_key_and_never_submits(tmp_path):
    seen = []
    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(422,json={'error':{'code':'invalid_image'}})
    with pytest.raises(SparkProviderError) as error:
        await SparkVideoClient('https://spark.test','secret',output_dir=tmp_path,transport=httpx.MockTransport(handler)).generate(
            VideoGenerationRequest(prompt='animate',first_frame_data_url=DATA,idempotency_key='stable'))
    assert error.value.idempotency_key == 'stable'
    assert error.value.code == 'invalid_image'
    assert seen == ['/v1/assets']


@pytest.mark.parametrize('value',['https://test/img.png','data:image/svg+xml;base64,YQ==','data:image/png;base64,???','data:image/png;base64,'])
def test_reject_nonbinary_image_sources(value):
    with pytest.raises(ValueError):
        decode_image_data_url(value)


def test_source_selection_and_schema_conflicts():
    images = [attachment(),attachment()]
    assert attachment_image(images,2) == DATA
    with pytest.raises(ValueError):
        attachment_image(images)
    with pytest.raises(ValueError):
        attachment_image(images,3)
    for invalid in (True, 1.0, '1', 0):
        with pytest.raises(ValueError):
            attachment_image(images,invalid)
    with pytest.raises(ValidationError):
        VideoGenerationRequest(prompt='a',first_frame_asset_id=ASSET,image_attachment_index=1)
    with pytest.raises(ValidationError):
        ImageGenerationRequest(prompt='a',mode='text_to_image',image_data_url=DATA)
    with pytest.raises(ValidationError):
        ImageGenerationRequest(prompt='a',mode='image_to_image',denoise=True)
    assert spark_image_options({},[attachment()]) == {'mode':'image_to_image','image_data_url':DATA}
    assert spark_image_options({'mode':'text_to_image'},images) == {'mode':'text_to_image'}
    assert spark_image_options({'image_asset_id':ASSET},images) == {'image_asset_id':ASSET}
    assert spark_image_options({'image_attachment_index':2},images)['image_data_url'] == DATA


@pytest.mark.asyncio
async def test_tools_expose_attachment_selection_without_base64():
    for skill in [GenerateImageSkill(),GenerateVideoSkill()]:
        props = skill.to_tool_definition()['parameters']['properties']
        assert 'image_attachment_index' in props and 'image_fit' in props
        assert 'image_data_url' not in props and 'first_frame_data_url' not in props
    options = await GenerateImageSkill().prepare_arguments(prompt='a',provider='spark',image_attachment_index=1)
    assert options['mode'] == 'image_to_image'


@pytest.mark.asyncio
@pytest.mark.parametrize('denied',[False,True])
async def test_engine_video_resolves_attachment_inside_governance(engine,denied):
    request = ChatRequest(conversation_id='image-input',agent_id='super_chat',message='让图片动起来',
        attachments=[attachment()],tool_policies={'generate_video':'deny' if denied else 'auto'})
    with patch('agent.skills.builtin.generate_video.generate_video',new=AsyncMock(return_value=video_response())) as generate:
        result = await engine._execute_skill_with_governance(request=request,run_id='image-input-run',
            skill_name='generate_video',arguments={'prompt':'animate','mode':'image_to_video','image_attachment_index':1})
    if denied:
        generate.assert_not_called()
        assert not result.success
    else:
        assert result.success
        called = generate.await_args.args[0]
        assert called.first_frame_data_url == DATA and called.image_attachment_index is None
        redacted = engine._tool_arguments_for_trace('generate_video',called.model_dump())
        assert DATA not in json.dumps(redacted)


@pytest.mark.asyncio
async def test_image_workflow_forwards_selected_attachment_and_strength(engine):
    from agent.llm.base import LLMResponse, ToolCall
    from agent.schemas.aigc import GeneratedImage, ImageGenerationResponse
    delegate=LLMResponse(content='',model='test',tool_calls=[ToolCall(id='redraw',name='image_generation_v1',arguments={
        'task':'将第二张图改成水彩','reason':'用户要求基于原图重绘','provider':'spark',
        'mode':'image_to_image','image_attachment_index':2,'denoise':.3,'image_fit':'stretch'})])
    review=LLMResponse(content='{"should_generate":true,"final_prompt":"watercolor cube","aspect_ratio":"1:1"}',model='test',tool_calls=[])
    final=LLMResponse(content='已生成。',model='test',tool_calls=[])
    llm=AsyncMock()
    llm.chat=AsyncMock(side_effect=[delegate,review,final])
    image=ImageGenerationResponse(id='redraw-result',provider='spark',model='z-image-base',prompt='watercolor cube',
        aspect_ratio='1:1',response_format='url',images=[GeneratedImage(index=0,url='/static/generated/aigc/redraw.png')])
    with patch.object(engine,'_get_provider',return_value=llm), patch('agent.orchestrator.engine.generate_image_with_provider',
            new=AsyncMock(return_value=image)) as generate:
        result=await engine.process(ChatRequest(conversation_id='redraw-workflow',agent_id='super_chat',message='将第二张图改成水彩',
            attachments=[ChatAttachment(name='notes.txt',kind='text',content='notes'),attachment()],memory_enabled=False))
    called=generate.await_args.args[0]
    assert (called.mode,called.image_data_url,called.denoise,called.image_fit)==('image_to_image',DATA,.3,'stretch')
    assert called.subject_reference is None
    assert '/static/generated/aigc/redraw.png' in result.response


@pytest.mark.asyncio
async def test_spark_options_cannot_silently_fall_back_to_minimax():
    with pytest.raises(ValueError,match='provider=spark'):
        await GenerateImageSkill().prepare_arguments(prompt='a',provider='minimax',image_attachment_index=1,denoise=.3)
    from agent.aigc.image_service import generate_image
    with pytest.raises(ValueError,match='provider=spark'):
        await generate_image(ImageGenerationRequest(prompt='a',provider='minimax',image_asset_id=ASSET))


@pytest.mark.parametrize('source', ['image_asset_id', 'image_data_url'])
def test_image_workflow_rejects_attachment_and_explicit_source(source):
    with pytest.raises(ValueError, match='Choose one image source'):
        spark_image_options({source: ASSET if source == 'image_asset_id' else DATA,
                             'image_attachment_index': 1}, [attachment()])


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['image', 'video'])
async def test_null_historical_mode_falls_back_to_requested_mode(tmp_path, kind):
    def handler(request):
        if request.method == 'POST':
            task = image_task(mode=None, source=None) if kind == 'image' else video_task(mode=None, source=None)
            return httpx.Response(202, json=task)
        return httpx.Response(200, content=png() if kind == 'image' else mp4(),
                              headers={'Content-Type': 'image/png' if kind == 'image' else 'video/mp4'})
    options = dict(base_url='https://spark.test', api_key='secret', output_dir=tmp_path,
                   transport=httpx.MockTransport(handler))
    if kind == 'image':
        result = await SparkImageClient(**options).generate(ImageGenerationRequest(prompt='redraw', image_asset_id=ASSET))
    else:
        result = await SparkVideoClient(**options).generate(VideoGenerationRequest(prompt='animate', first_frame_asset_id=ASSET))
    assert result.metadata['mode'] == 'image_to_' + kind
    assert result.metadata['source'] is None
