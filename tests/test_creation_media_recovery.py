"""Creation must keep provider task identity across long waits and retries."""
import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from agent.aigc import creation, creation_media_state as state
from agent.aigc.progress import background_enabled, emit_progress
from agent.aigc.spark_client import SparkProviderError


def request(**kwargs):
    return creation.CreationNodeRequest(kind='video',prompt='mist over forest',idempotency_key='original-run',**kwargs)


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch,tmp_path):
    monkeypatch.setattr(state,'STATE_DIR',tmp_path/'state')
    monkeypatch.setattr(creation,'OUTPUT_DIR',tmp_path)


@pytest.mark.asyncio
async def test_accepted_task_survives_timeout_and_resumes_without_new_submission(monkeypatch,tmp_path):
    async def first(req, **kwargs):
        assert background_enabled()
        assert not kwargs.get('resume_task_id')
        emit_progress(kind='video',stage='running',task_id='original-task',idempotency_key=req.idempotency_key)
        raise SparkProviderError('internal detail',code='wait_timeout',task_id='original-task')
    monkeypatch.setattr(creation,'generate_video',first)
    with pytest.raises(SparkProviderError):await creation.execute_node(request())
    (tmp_path/'saved.mp4').write_bytes(b'mp4')
    async def resumed(req, **kwargs):
        assert kwargs == {'resume_task_id':'original-task'}
        assert background_enabled()
        return SimpleNamespace(id='original-task',videos=[SimpleNamespace(url='/static/generated/aigc/saved.mp4')])
    monkeypatch.setattr(creation,'generate_video',resumed)
    result=await creation.execute_node(request())
    assert result['provider_task_id']=='original-task'
    assert base64.b64decode(result['content'])==b'mp4'
    assert not background_enabled()
    assert 'mist over forest' not in next((tmp_path/'state').glob('*.json')).read_text()
    altered=request();altered.prompt='a different film'
    with pytest.raises(ValueError,match='上下文已变化'):await creation.execute_node(altered)


@pytest.mark.asyncio
async def test_creation_api_preserves_safe_timeout_diagnostics(monkeypatch):
    from agent.main import app
    monkeypatch.setattr(creation,'execute_node',AsyncMock(side_effect=SparkProviderError('SECRET',code='wait_timeout',task_id='original-task')))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/agent/creation/node',json=request().model_dump())
    assert response.status_code==504
    detail=response.json()['detail']
    assert detail['code']=='media_wait_timeout' and detail['provider_task_id']=='original-task'
    assert 'SECRET' not in response.text


@pytest.mark.asyncio
async def test_task_inspection_only_returns_safe_status(monkeypatch):
    from agent.main import app
    inspect=AsyncMock(return_value=dict(id='task-id',type='video',status='running',progress_percent=75,input={'prompt':'PRIVATE'},error={'message':'SECRET'}))
    monkeypatch.setattr(creation,'video_task_status',inspect)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/agent/creation/video-task/task-id')
    assert response.status_code==200 and response.json()['status']=='running'
    assert response.json()['progress_percent']==75
    assert 'PRIVATE' not in response.text and 'SECRET' not in response.text


@pytest.mark.asyncio
async def test_creation_waits_beyond_poll_window_without_submitting_again(monkeypatch,tmp_path):
    from agent.aigc.spark_video_client import SparkVideoClient
    from tests.test_spark_video import task, mp4
    calls=[]
    polls=0
    async def handler(req):
        nonlocal polls
        calls.append(req.method)
        if req.method=='POST':return httpx.Response(202,json=task('running'))
        if '/artifacts/' in req.url.path:return httpx.Response(200,content=mp4(),headers={'Content-Type':'video/mp4'})
        polls+=1
        if polls==1:await asyncio.sleep(.03)
        return httpx.Response(200,json=task())
    async def generate(req,**kwargs):
        client=SparkVideoClient('https://spark.test','test',output_dir=tmp_path,timeout=.01,poll_interval=0,transport=httpx.MockTransport(handler))
        return await client.generate(req,**kwargs)
    monkeypatch.setattr(creation,'generate_video',generate)
    result=await asyncio.wait_for(creation.execute_node(request()),1)
    assert result['provider_task_id']=='video-task'
    assert calls.count('POST')==1 and polls>=2


@pytest.mark.asyncio
async def test_provider_task_inspection_never_submits_or_downloads(tmp_path):
    from agent.aigc.spark_video_client import SparkVideoClient
    from tests.test_spark_video import task
    calls=[]
    def handler(req):
        calls.append((req.method,req.url.path))
        return httpx.Response(200,json=task('running'))
    client=SparkVideoClient('https://spark.test','test',output_dir=tmp_path,transport=httpx.MockTransport(handler))
    assert (await client.inspect_task('video-task'))['status']=='running'
    assert calls==[('GET','/v1/tasks/video-task')]
    assert not list(tmp_path.iterdir())
