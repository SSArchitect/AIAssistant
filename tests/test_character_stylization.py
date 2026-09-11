import json
from unittest.mock import patch

import httpx
import pytest

from agent.aigc.image_inputs import spark_image_options
from agent.aigc.spark_client import SparkImageClient
from agent.schemas.aigc import ImageGenerationRequest
from agent.skills.builtin.generate_image import GenerateImageSkill
from tests.test_spark_image_inputs import ASSET, DATA, attachment
from tests.test_spark_image import png, task


@pytest.mark.parametrize('style',['anime','chibi'])
@pytest.mark.asyncio
async def test_character_upload_payload_result(tmp_path, style):
    seen=[]
    def handle(request):
        if request.url.path == '/v1/assets':
            assert request.content == png(320,240)
            seen.append('upload')
            return httpx.Response(201,json={'id':ASSET,'status':'ready'})
        if request.method == 'POST':
            data=json.loads(request.content)
            assert data['mode']=='character_stylization'
            assert data['input']['character_style']==style
            assert data['input']['image_asset_id']==ASSET
            assert 'denoise' not in data['input']
            seen.append('task')
            result=task()
            result.update(mode='character_stylization',stylization={'style':style,'model':'Qwen-Image-Edit-2511'})
            return httpx.Response(202,json=result)
        return httpx.Response(200,content=png(),headers={'Content-Type':'image/png'})
    options=spark_image_options({'character_style':style},[attachment()])
    request=ImageGenerationRequest(prompt='keep outfit',provider='spark',**options)
    result=await SparkImageClient('https://spark.test','secret',output_dir=tmp_path,transport=httpx.MockTransport(handle)).generate(request)
    assert seen==['upload','task']
    assert result.model=='qwen-image-edit-2511'
    assert result.metadata['stylization']['style']==style


@pytest.mark.parametrize('extra',[{'denoise':.5},{'mode':'text_to_image'},{'mode':'image_to_image'},
                                  {'character_style':'invalid'},{'image_asset_id':None}])
def test_invalid_character_options(extra):
    options={'prompt':'a','image_asset_id':ASSET,'character_style':'anime',**extra}
    with pytest.raises(ValueError):
        ImageGenerationRequest(**options)


def test_character_dimensions_and_attachment_selection():
    request=ImageGenerationRequest(prompt='a',image_asset_id=ASSET,character_style='chibi',aspect_ratio='9:16')
    assert SparkImageClient.payload(request)['input']['height']==1024
    with pytest.raises(ValueError):
        SparkImageClient.payload(request.model_copy(update={'width':2048,'height':1024}))
    with pytest.raises(ValueError):
        spark_image_options({'character_style':'anime'},[attachment(),attachment()])
    options=spark_image_options({'character_style':'anime','image_attachment_index':2},[attachment(),attachment()])
    assert options['mode']=='character_stylization' and options['image_data_url']==DATA


@pytest.mark.asyncio
async def test_tool_styles_and_other_provider_rejection():
    skill=GenerateImageSkill()
    assert next(p for p in skill.metadata().parameters if p.name=='character_style').enum==['anime','chibi']
    with pytest.raises(ValueError):
        await skill.prepare_arguments(prompt='a',provider='minimax',image_asset_id=ASSET,character_style='anime')
    args=await skill.prepare_arguments(prompt='a',provider='spark',image_asset_id=ASSET,character_style='anime')
    assert args['mode']=='character_stylization' and args['idempotency_key']


@pytest.mark.asyncio
async def test_character_workflow_forwards_selected_attachment_and_style(engine):
    from unittest.mock import AsyncMock
    from agent.schemas.chat import ChatRequest, ChatAttachment
    from agent.llm.base import LLMResponse, ToolCall
    from agent.schemas.aigc import GeneratedImage, ImageGenerationResponse
    delegate=LLMResponse(content='',model='test',tool_calls=[ToolCall(id='redraw',name='image_generation_v1',arguments={
        'task':'将第二张图改成水彩','reason':'用户要求基于原图重绘','provider':'spark',
        'mode':'character_stylization','character_style':'chibi','image_attachment_index':2,'image_fit':'stretch'})])
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
    assert (called.mode,called.image_data_url,called.character_style,called.denoise,called.image_fit)==('character_stylization',DATA,'chibi',None,'stretch')
    assert called.subject_reference is None
    assert '/static/generated/aigc/redraw.png' in result.response
