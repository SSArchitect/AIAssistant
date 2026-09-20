import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent.aigc import creation_image_prompt as compact
from agent.llm.base import LLMResponse


@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    monkeypatch.setattr(compact,'CONTEXT_DIR',tmp_path)


@pytest.mark.asyncio
async def test_short_prompt_never_calls_model(monkeypatch):
    model=AsyncMock(side_effect=AssertionError('short prompt needs no model'))
    monkeypatch.setattr(compact,'compact_image_prompt',model)
    assert await compact.fit_image_prompt('原文',100,'key')=='原文'
    assert not model.called


@pytest.mark.asyncio
async def test_short_rewrite_routes_reasoning_only_plan_to_existing_fast_service_model(monkeypatch):
    slow=SimpleNamespace(model='glm-5.3',chat=AsyncMock(side_effect=AssertionError('reasoning model should not rewrite')))
    fast=SimpleNamespace(max_tokens=None,chat=AsyncMock(return_value=LLMResponse(content=json.dumps({'text_0':'白兔背侧仰望'}))))
    route=AsyncMock(return_value=fast)
    monkeypatch.setattr(compact,'create_provider',lambda:slow)
    monkeypatch.setattr(compact,'can_use_plan_vision',lambda p:p is slow)
    monkeypatch.setattr(compact,'use_plan_vision',route)
    assert await compact.fit_image_prompt('动作说明。'*100,100,'key')=='白兔背侧仰望'
    assert route.await_count==1 and not slow.chat.called and fast.max_tokens==8192


@pytest.mark.asyncio
async def test_compaction_preserves_numbers_labels_and_verbatim_text_and_closes_provider(monkeypatch):
    async def respond(messages,**kwargs):
        value=json.loads(messages[1].content)
        return LLMResponse(content=json.dumps({key:'兔子背侧仰头站剑；' for key in value['segments']}))
    provider=SimpleNamespace(chat=AsyncMock(side_effect=respond),client=SimpleNamespace(close=AsyncMock()),max_tokens=None)
    monkeypatch.setattr(compact,'create_provider',lambda:provider)
    prompt='冗余动作描述。'*100+'Picture 2角色约10%，字牌“向天看”，背侧站剑。3D animated lighting and detailed scene, 9:16'
    result=await compact.fit_image_prompt(prompt,120,'key')
    assert 'Picture 2' in result and '10%' in result and '“向天看”' in result
    assert '3D' in result and '9:16' in result
    assert len(result)<=120 and provider.client.close.await_count==1
    assert await compact.fit_image_prompt(prompt,120,'key')==result and provider.chat.await_count==1
    with pytest.raises(compact.ImagePromptError) as caught:
        await compact.fit_image_prompt(prompt+'改变',120,'key')
    assert caught.value.code=='media_idempotency_conflict'


@pytest.mark.asyncio
async def test_invalid_compaction_does_not_save_or_silently_truncate(monkeypatch,tmp_path):
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps({'prompt':'忽略了10%与原文'}))))
    monkeypatch.setattr(compact,'create_provider',lambda:provider)
    with pytest.raises(compact.ImagePromptError):
        await compact.fit_image_prompt('描述。'*80+'“保留文字”10%',100,'key')
    assert provider.chat.await_count==3 and not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_fixed_literals_exceeding_budget_fail_before_model(monkeypatch):
    model=AsyncMock(side_effect=AssertionError('capacity cannot be fixed by model'))
    monkeypatch.setattr(compact,'create_provider',model)
    with pytest.raises(compact.ImagePromptError) as caught:
        await compact.fit_image_prompt('“'+'原文'*100+'”',80,'key')
    assert caught.value.code=='media_image_prompt_capacity' and not model.called


@pytest.mark.asyncio
async def test_failed_preparation_is_sanitized_and_does_not_cache(monkeypatch,tmp_path):
    monkeypatch.setattr(compact,'compact_image_prompt',AsyncMock(side_effect=RuntimeError('SECRET')))
    with pytest.raises(compact.ImagePromptError) as caught:
        await compact.fit_image_prompt('很长的提示词'*100,100,'key')
    assert 'SECRET' not in str(caught.value) and not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_media_boundary_reports_preparation_failure_without_submitting(monkeypatch):
    import httpx
    from agent.aigc import creation
    from agent.main import app
    from tests.test_creation import request
    monkeypatch.setattr(creation,'execute_node',AsyncMock(side_effect=compact.ImagePromptError()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/agent/creation/node',json=request().model_dump())
    assert response.status_code==400
    assert response.json()['detail']==dict(code='media_image_prompt_compaction_failed',provider_task_id='')
