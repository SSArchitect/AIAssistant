import base64
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from agent.aigc import creation_review as review
from agent.llm.base import LLMResponse
from agent.trace.store import TraceStore
from tests.test_creation_planning import plan


def request(**kw):
    return review.ReviewRequest(project_id='p',user_id='alice',messages=[{'role':'user','content':'生成短片'}],current_plan=plan(),node_id='script',**kw)


@pytest.mark.asyncio
async def test_review_only_returns_a_decision_and_preserves_user_plan(monkeypatch):
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps({'decision':'approve','reason':'分镜清楚','asset_id':''}),model='test')))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    req=request();before=req.model_dump();trace=TraceStore()
    result=await review.review_creation(req,trace)
    assert result.decision=='approve' and req.model_dump()==before
    assert provider.chat.call_args.kwargs['tools'] is None
    assert not hasattr(result,'plan') and not hasattr(result,'approved_revision')
    assert trace.get_run(result.run_id).status=='completed'


@pytest.mark.asyncio
async def test_candidate_selection_receives_real_previews_and_rejects_foreign_ids(monkeypatch):
    content=BytesIO();Image.new('RGB',(8,8),'red').save(content,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()
    req=request(assets=[dict(id='chosen',name='候选图',mime_type='image/png',data_url=data)],candidate_ids=['chosen'])
    req.current_plan['nodes'].insert(0,dict(id='image',kind='image',title='主视觉',prompt='red square'));req.node_id='image'
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(content=json.dumps({'decision':'select','asset_id':'foreign','reason':'选这张'})),LLMResponse(content=json.dumps({'decision':'select','asset_id':'chosen','reason':'符合构图'}))]))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(req)
    assert result.asset_id=='chosen' and provider.chat.await_count==2
    user=provider.chat.call_args.args[0][1].content
    assert any(part['type']=='image_url' for part in user)
    req.candidate_ids=['foreign']
    with pytest.raises(ValueError,match='缺失'):await review.review_creation(req)


@pytest.mark.asyncio
async def test_failed_review_closes_trace_without_leaking_provider_secret(monkeypatch):
    provider=SimpleNamespace(chat=AsyncMock(side_effect=RuntimeError('SECRET')))
    monkeypatch.setattr(review,'create_provider',lambda:provider);trace=TraceStore()
    with pytest.raises(RuntimeError):await review.review_creation(request(),trace)
    assert all(r.status=='failed' and 'SECRET' not in r.error_message for r in trace._runs.values())


@pytest.mark.asyncio
async def test_reasoning_only_reviewer_omits_unsupported_switch_and_budgets_reasoning(monkeypatch):
    provider=SimpleNamespace(provider_name='doubao',model='glm-5.3',max_tokens=None,
        chat=AsyncMock(return_value=LLMResponse(content=json.dumps({'decision':'approve','reason':'符合要求','asset_id':''}))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(request())
    assert result.decision=='approve' and 'thinking_enabled' not in provider.chat.call_args.kwargs
    assert provider.max_tokens==8192


@pytest.mark.asyncio
async def test_review_reports_missing_configuration_without_format_error_or_secret(monkeypatch):
    def missing_provider():
        raise ValueError('missing key SECRET-UPSTREAM')
    monkeypatch.setattr(review, 'create_provider', missing_provider)
    from agent.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/agent/creation/review', json=request().model_dump())
    assert response.status_code == 502
    assert response.json()['detail']['code'] == 'provider_config_missing'
    assert '配置' in response.text and 'SECRET' not in response.text and '格式' not in response.text


@pytest.mark.asyncio
async def test_quality_failure_requests_revision_instead_of_stopping_or_approving(monkeypatch):
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps({'decision':'revise','reason':'小伞是蘑菇生物，候选错误混入兔大侠的服饰','asset_id':''}))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    req=request();before=req.model_dump()
    result=await review.review_creation(req)
    assert result.decision=='revise' and req.model_dump()==before
    assert provider.chat.await_count==1
    assert 'revise' in provider.chat.call_args.args[0][0].content


@pytest.mark.asyncio
async def test_revision_must_not_approve_any_candidate(monkeypatch):
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(content=json.dumps({'decision':'revise','reason':'需要重做','asset_id':'some-image'})),
        LLMResponse(content=json.dumps({'decision':'revise','reason':'需要重做','asset_id':''}))]))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(request())
    assert result.decision=='revise' and result.asset_id=='' and provider.chat.await_count==2


@pytest.mark.asyncio
async def test_review_isolates_sibling_repairs_and_labels_actual_reference_images(monkeypatch):
    content=BytesIO();Image.new('RGB',(8,8),'red').save(content,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()
    req=request(assets=[dict(id=i,name=i+'.png',mime_type='image/png',data_url=data)
        for i in ['candidate','identity','scene-result','unrelated']],candidate_ids=['candidate'],
        node_context={'scene':{'approved':True,'selected_asset_id':'scene-result'},
            'script':{'approved':True},'other':{'approved':False}},locked_node_ids=['script','scene'])
    req.current_plan['nodes'] = [req.current_plan['nodes'][0],
        dict(id='scene',kind='image',purpose='scene',title='已确认场景',prompt='发光孢子带尾迹',depends_on=['script']),
        dict(id='other',kind='image',title='另一张返工草稿',prompt='UNRELATED_REPAIR: 所有孢子绝不能有尾迹',asset_id='unrelated'),
        dict(id='shot',kind='image',purpose='shot_reference',title='触碰孢子',prompt='指尖触碰孢子',depends_on=['script','scene'],
             references=[dict(asset_id='identity',role='identity',note='人物与道具'),
                         dict(node_id='scene',role='environment',note='孢子形态与云海')])]
    req.messages.extend([
        dict(role='assistant',content='UNRELATED_REPAIR: 我推断全项目不能有尾迹'),
        dict(role='user',node_id='other',content='UNRELATED_REPAIR: 仅此节点取消尾迹'),
        dict(role='user',node_id='shot',content='保持当前场景中的孢子形态')])
    req.node_id='shot';before=req.model_dump()
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(
        {'decision':'select','asset_id':'candidate','reason':'符合已确认场景与动作'}))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(req)
    parts=provider.chat.call_args.args[0][1].content
    payload=json.loads(parts[0]['text'])
    assert [n['id'] for n in payload['current_plan']['nodes']]==['script','scene','shot']
    assert 'UNRELATED_REPAIR' not in json.dumps(parts,ensure_ascii=False)
    assert [m['content'] for m in payload['messages']]==['生成短片','保持当前场景中的孢子形态']
    assert set(payload['node_context'])=={'script','scene'}
    assert {a['id'] for a in payload['assets']}=={'candidate','identity','scene-result'}
    assert len([p for p in parts if p['type']=='image_url'])==3
    bindings=payload['review_references']
    assert [(r['asset_id'],r['role']) for r in bindings]==[('identity','identity'),('scene-result','environment')]
    assert bindings[1]['source_node_id']=='scene' and bindings[1]['source_approved'] is True
    labels=[p['text'] for p in parts[1:] if p['type']=='text']
    assert any('candidate' in label and '候选' in label for label in labels)
    assert any('scene-result' in label and 'environment' in label and '已确认' in label for label in labels)
    assert result.asset_id=='candidate' and req.model_dump()==before


@pytest.mark.asyncio
async def test_review_marks_unavailable_reference_as_unseen_and_keeps_video_dependencies(monkeypatch):
    req=request(assets=[dict(id='rabbit',name='人设.png',mime_type='image/png')])
    req.current_plan=plan('identity');req.node_id='video'
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(
        {'decision':'approve','reason':'执行方案自洽','asset_id':''}))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    await review.review_creation(req)
    parts=provider.chat.call_args.args[0][1].content;payload=json.loads(parts[0]['text'])
    assert [n['id'] for n in payload['current_plan']['nodes']]==['script','video']
    assert payload['review_references'][0]['asset_id']=='rabbit'
    assert payload['review_references'][0]['preview_available'] is False
    assert payload['assets'][0]['preview_available'] is False
    assert not any(p['type']=='image_url' for p in parts)
