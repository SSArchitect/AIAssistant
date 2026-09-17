import base64
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
