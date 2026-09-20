import base64
import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from agent.aigc.spark_client import SparkImageClient, SparkProviderError
from agent.schemas.aigc import ImageGenerationRequest
from tests.test_spark_image import png, task, make_client


def image(index):
    return 'data:image/png;base64,' + base64.b64encode(png(512+index,512)).decode()


def request(count=2, **kwargs):
    return ImageGenerationRequest(prompt='Picture 1 person in Picture 2 environment',mode='reference_to_image',
        reference_image_data_urls=[image(i) for i in range(count)],idempotency_key='storyboard-shot',**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('count',[1,2,3])
async def test_ordered_reference_uploads_generate_single_picture_and_resume_by_get(tmp_path,count):
    seen=[]; ids=[f'00000000-0000-4000-8000-{i:012d}' for i in range(count)]
    def handler(req):
        seen.append(req)
        if req.url.path=='/v1/templates':
            return httpx.Response(200,json={'templates':[{'id':'image.reference.v1','enabled':True}]})
        if req.url.path=='/v1/assets':
            index=sum(r.url.path=='/v1/assets' for r in seen)-1
            assert req.content==base64.b64decode(image(index).split(',')[1])
            assert req.headers['content-type']=='image/png'
            return httpx.Response(201,json={'id':ids[index],'status':'ready'})
        if req.method=='POST':
            payload=json.loads(req.content)
            assert payload['template']=='image.reference.v1' and payload['mode']=='reference_to_image'
            assert payload['input']['reference_image_asset_ids']==ids
            assert not {'image_asset_id','denoise','image_fit','character_style'} & payload['input'].keys()
            return httpx.Response(202,json=task())
        if '/artifacts/' in req.url.path: return httpx.Response(200,content=png(),headers={'Content-Type':'image/png'})
        return httpx.Response(200,json=task())
    result=await make_client(tmp_path,handler).generate(request(count))
    assert result.model=='qwen-image-edit-2511' and result.id=='task-123'
    keys=[r.headers['idempotency-key'] for r in seen if r.url.path=='/v1/assets']
    assert len(keys)==len(set(keys))==count
    seen.clear()
    await make_client(tmp_path,handler).generate(request(count),resume_task_id='task-123')
    assert len(seen)==2 and all(r.method=='GET' for r in seen) and all('/v1/tasks/task-123' in r.url.path for r in seen)


@pytest.mark.parametrize('kwargs',[{'reference_image_data_urls':[]},{'reference_image_data_urls':[image(0)]*2},
    {'reference_image_data_urls':[image(i) for i in range(4)]},{'image_data_url':image(0)},
    {'image_fit':'center_crop'},{'denoise':.5},{'character_style':'chibi'}, {'mode':'image_to_image'}])
def test_invalid_reference_contract_rejected(kwargs):
    value=dict(prompt='x',mode='reference_to_image',reference_image_data_urls=[image(0),image(1)])
    value.update(kwargs)
    with pytest.raises(ValidationError):ImageGenerationRequest(**value)


def test_reference_canvas_uses_one_megapixel_budget_and_exact_requested_dimensions():
    assert SparkImageClient.dimensions(request(aspect_ratio='16:9'))==(1024,576)
    assert SparkImageClient.dimensions(request(width=1344,height=768))==(1344,768)
    with pytest.raises(ValueError):SparkImageClient.payload(request(width=1536,height=864))
    with pytest.raises(ValueError):SparkImageClient.payload(request(width=1000,height=1000))


@pytest.mark.asyncio
async def test_disabled_template_stops_before_upload_or_task(tmp_path):
    def handler(req):
        assert req.method=='GET' and req.url.path=='/v1/templates'
        return httpx.Response(200,json={'templates':[{'id':'image.reference.v1','enabled':False}]})
    with pytest.raises(SparkProviderError,match='reference') as caught:
        await make_client(tmp_path,handler).generate(request())
    assert caught.value.code=='unsupported_task_type'


@pytest.mark.asyncio
async def test_uncertain_submission_retries_same_order_bytes_and_seed(tmp_path):
    submitted=[];uploads=[]
    def handler(req):
        if req.url.path=='/v1/templates':return httpx.Response(200,json={'templates':[{'id':'image.reference.v1','enabled':True}]})
        if req.url.path=='/v1/assets':
            uploads.append(req)
            return httpx.Response(201,json={'id':f'00000000-0000-4000-8000-{len(uploads):012d}','status':'ready'})
        if req.method=='POST':
            submitted.append(req)
            if len(submitted)==1:raise httpx.ReadTimeout('lost acknowledgement')
            return httpx.Response(202,json=task())
        return httpx.Response(200,content=png(),headers={'Content-Type':'image/png'})
    with patch('agent.aigc.spark_client.asyncio.sleep',new=AsyncMock()):
        await make_client(tmp_path,handler).generate(request(3))
    assert len(uploads)==3 and len(submitted)==2
    assert submitted[0].content==submitted[1].content and submitted[0].headers['idempotency-key']==submitted[1].headers['idempotency-key']
    assert json.loads(submitted[0].content)['input']['seed'] is None


@pytest.mark.asyncio
async def test_three_reference_uploads_have_budget_before_task_acknowledgement(tmp_path, monkeypatch):
    from agent.aigc.progress import progress_scope
    monkeypatch.setattr('agent.aigc.spark_client.SUBMISSION_TIMEOUT', .3)
    uploads, tasks = [], []
    async def handler(req):
        if req.url.path=='/v1/templates':
            return httpx.Response(200,json={'templates':[{'id':'image.reference.v1','enabled':True}]})
        if req.url.path=='/v1/assets':
            uploads.append(req)
            await asyncio.sleep(.12)
            return httpx.Response(201,json={'id':f'00000000-0000-4000-8000-{len(uploads):012d}','status':'ready'})
        if req.method=='POST':
            tasks.append(req)
            return httpx.Response(202,json=task())
        return httpx.Response(200,content=png(),headers={'Content-Type':'image/png'})
    client=make_client(tmp_path,handler)
    with progress_scope(lambda event:None, background=True):
        result=await client.generate(request(3))
    assert result.id=='task-123' and len(uploads)==3 and len(tasks)==1


@pytest.mark.asyncio
async def test_reference_upload_deadline_is_bounded_without_acknowledged_task(tmp_path, monkeypatch):
    from agent.aigc.progress import progress_scope
    monkeypatch.setattr('agent.aigc.spark_client.SUBMISSION_TIMEOUT', .01)
    calls=[]
    async def handler(req):
        calls.append(req)
        await asyncio.sleep(1)
        raise AssertionError('Missing submission deadline')
    client=make_client(tmp_path,handler)
    with progress_scope(lambda event:None, background=True):
        with pytest.raises(SparkProviderError) as caught:
            await asyncio.wait_for(client.generate(request(3)),.3)
    assert caught.value.code=='wait_timeout' and caught.value.task_id is None
    assert len(calls)==1
