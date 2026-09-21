"""Uploads acknowledged before a failed submission survive client/process recreation."""
import asyncio
import json
import pytest
import httpx
from agent.aigc.spark_client import SparkImageClient, SparkProviderError
from agent.aigc.progress import progress_scope
from tests.test_spark_reference_image import request
from tests.test_spark_image import png, task


def client(tmp_path, handler, **kwargs):
    return SparkImageClient('https://spark.test', 'private-secret', output_dir=tmp_path/'outputs',
        upload_cache_dir=tmp_path/'uploads', transport=httpx.MockTransport(handler), poll_interval=0, **kwargs)


@pytest.mark.asyncio
async def test_recreated_client_skips_acknowledged_upload_after_submission_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr('agent.aigc.spark_client.SUBMISSION_TIMEOUT', .02)
    uploads=[]; first=True; submissions=[]
    async def handler(req):
        if req.url.path=='/v1/templates':return httpx.Response(200,json={'templates':[{'id':'image.reference.v1','enabled':True}]})
        if req.url.path=='/v1/assets':
            uploads.append(req)
            return httpx.Response(201,json={'id':'00000000-0000-4000-8000-000000000001','status':'ready'})
        if req.method=='POST':
            submissions.append(req)
            if first:await asyncio.sleep(1)
            return httpx.Response(202,json=task())
        return httpx.Response(200,content=png(),headers={'Content-Type':'image/png'})
    with progress_scope(lambda _:None,background=True):
        with pytest.raises(SparkProviderError) as exc:await client(tmp_path,handler).generate(request(1))
    assert exc.value.code=='wait_timeout'
    first=False
    result=await client(tmp_path,handler).generate(request(1))
    assert result.id=='task-123' and len(uploads)==1
    assert submissions[0].content==submissions[1].content
    assert submissions[0].headers['idempotency-key']==submissions[1].headers['idempotency-key']
    saved=''.join(p.read_text() for p in (tmp_path/'uploads').glob('*.json'))
    assert 'private-secret' not in saved and 'data:image' not in saved


@pytest.mark.asyncio
async def test_upload_window_covers_slow_transport_and_total_submission_budget(tmp_path,monkeypatch):
    monkeypatch.setattr('agent.aigc.spark_client.SUBMISSION_TIMEOUT', .02)
    async def handler(req):
        if req.url.path=='/v1/templates':return httpx.Response(200,json={'templates':[{'id':'image.reference.v1','enabled':True}]})
        if req.url.path=='/v1/assets':
            assert req.extensions['timeout']['read']==.04
            assert req.extensions['timeout']['write']==.04
            await asyncio.sleep(.025)
            return httpx.Response(201,json={'id':'00000000-0000-4000-8000-000000000001','status':'ready'})
        if req.method=='POST':return httpx.Response(202,json=task())
        return httpx.Response(200,content=png(),headers={'Content-Type':'image/png'})
    c=client(tmp_path,handler)
    assert c.submission_timeout(request(3))==pytest.approx(.14)
    with progress_scope(lambda _:None,background=True):await c.generate(request(3))


@pytest.mark.asyncio
async def test_receipt_replays_expired_asset_and_rejects_changed_bytes(tmp_path):
    calls=[]
    async def handler(req):
        calls.append(req)
        return httpx.Response(201,json={'id':'00000000-0000-4000-8000-000000000001','status':'expired'})
    c=client(tmp_path,handler)
    async with httpx.AsyncClient(base_url='https://spark.test',transport=httpx.MockTransport(handler)) as http:
        first=await c._upload_asset(http,b'original','image/png','same-key')
        assert await client(tmp_path,handler)._upload_asset(http,b'original','image/png','same-key')==first
        with pytest.raises(SparkProviderError) as exc:await c._upload_asset(http,b'changed','image/png','same-key')
        assert exc.value.code=='idempotency_conflict'
    assert len(calls)==1


@pytest.mark.asyncio
async def test_invalid_or_failed_upload_is_never_checkpointed(tmp_path):
    async def handler(req):return httpx.Response(201,json={'id':'not-an-id','status':'ready'})
    async with httpx.AsyncClient(base_url='https://spark.test',transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SparkProviderError):await client(tmp_path,handler)._upload_asset(http,b'image','image/png','key')
    assert not list((tmp_path/'uploads').glob('*.json'))


def test_upload_cache_is_scoped_to_origin_and_credential(tmp_path):
    from agent.aigc.spark_uploads import UploadCache
    a=UploadCache(tmp_path,'https://one.test','secret-a')
    a.save('key',b'image','image/png','00000000-0000-4000-8000-000000000001')
    assert a.load('key',b'image','image/png')
    assert UploadCache(tmp_path,'https://two.test','secret-a').load('key',b'image','image/png') is None
    assert UploadCache(tmp_path,'https://one.test','secret-b').load('key',b'image','image/png') is None


@pytest.mark.asyncio
async def test_partial_upload_failure_keeps_first_receipt_and_order(tmp_path,monkeypatch):
    monkeypatch.setattr('agent.aigc.spark_client.SUBMISSION_TIMEOUT', .01)
    posted=[];first=True
    async def handler(req):
        if req.url.path=='/v1/templates':return httpx.Response(200,json={'templates':[{'id':'image.reference.v1','enabled':True}]})
        if req.url.path=='/v1/assets':
            key=req.headers['idempotency-key'];posted.append(key)
            if len(posted)==2 and first:await asyncio.sleep(1)
            ident='00000000-0000-4000-8000-00000000000'+('1' if key==posted[0] else '2')
            return httpx.Response(201,json={'id':ident,'status':'ready'})
        if req.method=='POST':
            assert json.loads(req.content)['input']['reference_image_asset_ids']==[
                '00000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000002']
            return httpx.Response(202,json=task())
        return httpx.Response(200,content=png(),headers={'Content-Type':'image/png'})
    with progress_scope(lambda _:None,background=True):
        with pytest.raises(SparkProviderError):await client(tmp_path,handler).generate(request(2))
    first=False
    await client(tmp_path,handler).generate(request(2))
    assert len(posted)==3 and posted[1]==posted[2] and posted.count(posted[0])==1


def test_incomplete_receipt_replays_original_upload(tmp_path):
    from agent.aigc.spark_uploads import UploadCache
    cache=UploadCache(tmp_path,'https://spark.test','key')
    cache.path('upload').write_text('{broken')
    assert cache.load('upload',b'original','image/png') is None


@pytest.mark.asyncio
async def test_production_image_service_enables_private_upload_receipts(tmp_path,monkeypatch):
    from unittest.mock import AsyncMock,patch
    from agent.aigc.image_service import generate_image
    from agent.schemas.aigc import ImageGenerationRequest
    monkeypatch.setattr('agent.aigc.image_service.UPLOAD_CACHE_DIR',tmp_path)
    with patch('agent.aigc.image_service.SparkImageClient') as factory:
        factory.return_value.generate=AsyncMock(return_value='ok')
        assert await generate_image(ImageGenerationRequest(provider='spark',prompt='tree'))=='ok'
        assert factory.call_args.kwargs['upload_cache_dir']==tmp_path
