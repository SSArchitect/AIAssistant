import base64
import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from agent.aigc.image_inputs import reference_video_options
from agent.aigc.spark_video_client import SparkVideoClient
from agent.schemas.aigc import VideoGenerationRequest
from agent.schemas.chat import ChatAttachment, ChatRequest
from agent.skills.builtin.generate_video import GenerateVideoSkill
from tests.test_spark_video import mp4, task, video_response
from tests.test_spark_image import png

IDS=[str(uuid.uuid4()),str(uuid.uuid4())]
DATA=['data:image/png;base64,'+base64.b64encode(png(width,240)).decode() for width in (320,640)]


def attachments():
    return [ChatAttachment(name=f'ref{i}.png',kind='image',type='image/png',data_url=value) for i,value in enumerate(DATA)]


def test_reference_selection_order_and_hidden_bytes():
    selected=reference_video_options({'reference_image_attachment_indices':[2,1]},attachments())
    assert selected['reference_image_data_urls']==DATA[::-1]
    assert VideoGenerationRequest(prompt='a',**selected).mode=='reference_to_video'
    properties=GenerateVideoSkill().to_tool_definition()['parameters']['properties']
    assert properties['reference_image_attachment_indices']['maxItems']==9
    assert 'reference_image_data_urls' not in properties
    for indices in ([],[1,1],[True],[0],[3],list(range(1,11))):
        with pytest.raises(ValueError):
            reference_video_options({'reference_image_attachment_indices':indices},attachments())


@pytest.mark.parametrize('extra',[
    {'reference_image_asset_ids':[]}, {'reference_image_asset_ids':['bad']},
    {'reference_image_asset_ids':IDS*5}, {'reference_image_asset_ids':[IDS[0]]*2},
    {'reference_image_asset_ids':IDS,'reference_image_attachment_indices':[1]},
    {'reference_image_asset_ids':IDS,'first_frame_asset_id':IDS[0]},
    {'reference_image_asset_ids':IDS,'image_fit':'stretch'},
    {'reference_image_asset_ids':IDS,'duration_seconds':16},
    {'reference_image_asset_ids':IDS,'mode':'text_to_video'},
    {'mode':'reference_to_video'},
])
def test_invalid_reference_options(extra):
    with pytest.raises(ValidationError):
        VideoGenerationRequest(prompt='a',**extra)


@pytest.mark.asyncio
async def test_ordered_uploads_and_idempotent_transport_retry(tmp_path):
    uploads=[]
    tasks=[]
    def handler(request):
        if request.url.path=='/v1/assets':
            uploads.append(request)
            index=0 if request.content==png(320,240) else 1
            if len(uploads)==1:
                raise httpx.ReadTimeout('lost response')
            return httpx.Response(201,json={'id':IDS[index],'status':'expired'})
        if request.method=='POST':
            body=json.loads(request.content)
            tasks.append(body)
            assert body['template']=='video.reference.v1'
            assert body['input']['reference_image_asset_ids']==IDS
            assert not any(k in body['input'] for k in ('reference_image_data_urls','reference_image_attachment_indices','image_fit'))
            return httpx.Response(202,json=task(mode='reference_to_video',references=[{'asset_id':i} for i in IDS]))
        return httpx.Response(200,content=mp4(),headers={'Content-Type':'video/mp4'})
    client=SparkVideoClient('https://spark.test','secret',output_dir=tmp_path,transport=httpx.MockTransport(handler),poll_interval=0)
    with patch('agent.aigc.spark_client.asyncio.sleep',new=AsyncMock()):
        result=await client.generate(VideoGenerationRequest(prompt='a',reference_image_data_urls=DATA,idempotency_key='stable'))
    assert len(tasks)==1
    assert uploads[0].headers['idempotency-key']==uploads[1].headers['idempotency-key']
    assert uploads[1].headers['idempotency-key']!=uploads[2].headers['idempotency-key']
    assert result.metadata['references']==[{'asset_id':i} for i in IDS]


@pytest.mark.asyncio
@pytest.mark.parametrize('denied',[False,True])
async def test_engine_reference_attachments_governance_and_redaction(engine,denied):
    request=ChatRequest(conversation_id='r2v',agent_id='super_chat',message='参考两张图生成视频',attachments=attachments(),
                        tool_policies={'generate_video':'deny' if denied else 'auto'})
    with patch('agent.skills.builtin.generate_video.generate_video',new=AsyncMock(return_value=video_response())) as generate:
        result=await engine._execute_skill_with_governance(request=request,run_id='r2v-run',skill_name='generate_video',
            arguments={'prompt':'Use <Picture 1> in <Picture 2>.','mode':'reference_to_video','reference_image_attachment_indices':[2,1]})
    if denied:
        generate.assert_not_called()
        assert not result.success
    else:
        assert result.success
        called=generate.await_args.args[0]
        assert called.reference_image_data_urls==DATA[::-1]
        assert called.reference_image_attachment_indices is None
        redacted=engine._tool_arguments_for_trace('generate_video',called.model_dump())
        assert all(value not in json.dumps(redacted) for value in DATA)


@pytest.mark.asyncio
async def test_url_sources_resolve_in_order():
    from agent.aigc.video_service import generate_video
    urls=['https://example.com/one.png','https://example.com/two.png']
    with patch('agent.aigc.image_inputs.load_image_url',new=AsyncMock(side_effect=DATA)) as load, \
         patch('agent.aigc.video_service.SparkVideoClient') as client:
        client.return_value.generate=AsyncMock(return_value=video_response())
        await generate_video(VideoGenerationRequest(prompt='a',reference_image_urls=urls))
    assert [call.args[0] for call in load.await_args_list]==urls
    sent=client.return_value.generate.await_args.args[0]
    assert sent.reference_image_data_urls==DATA and sent.reference_image_urls is None


@pytest.mark.asyncio
async def test_ninth_reference_is_visible_to_chat_model_and_selectable(engine):
    from agent.llm.base import LLMResponse
    images = [ChatAttachment(kind='image', name=f'ref-{i}.png',
        data_url='data:image/png;base64,' + base64.b64encode(png(320+i, 240)).decode()) for i in range(1, 10)]
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value=LLMResponse(content='ready', model='test'))
    with patch.object(engine, '_get_provider', return_value=llm):
        await engine.process(ChatRequest(conversation_id='nine-reference-images', agent_id='super_chat',
            message='参考这九张图生成视频', memory_enabled=False, attachments=images))
    messages = llm.chat.await_args.kwargs.get('messages') or llm.chat.await_args.args[0]
    content = next(message.content for message in messages if message.role == 'user' and isinstance(message.content, list))
    urls = [part['image_url']['url'] for part in content if part.get('type') == 'image_url']
    assert urls == [attachment.data_url for attachment in images]
    assert '## 9. ref-9.png' in engine._attachment_context_block(images)
    options = reference_video_options({'reference_image_attachment_indices': list(range(9, 0, -1))}, images)
    request = VideoGenerationRequest(prompt='nine images', **options)
    assert request.reference_image_data_urls == urls[::-1]
