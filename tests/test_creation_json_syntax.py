import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from agent.llm.base import LLMResponse


def parse(value):
    from agent.aigc.creation_json import parse_complete_object
    return parse_complete_object(value)


def test_missing_property_colons_preserve_all_values_and_order():
    original={'decision':'revise','asset_id':'','reason':'引用“原要求”，不要改写。','findings':[{'source_id':'target','observation':'他说 "朝上"，身体仍直立'}]}
    wire=json.dumps(original,ensure_ascii=False)
    malformed=wire.replace('"reason":','"reason"').replace('"source_id":','"source_id"')
    result,count=parse(malformed)
    assert result==original and count==2
    assert list(result)==list(original)
    assert parse(wire)==(original,0)


@pytest.mark.parametrize('wire',[
    '{"decision":"select","decision":"revise"}',
    '{"decision":"revise","reason":"unfinished',
    '{"decision":"revise","reason":"他说"朝上""}',
    '{"decision":"revise"} {"decision":"select"}',
    '[{"decision":"revise"}]',
    '{"score":NaN}',
])
def test_ambiguous_truncated_or_duplicate_content_is_not_reconstructed(wire):
    with pytest.raises(ValueError):parse(wire)


def test_repair_budget_is_bounded():
    with pytest.raises(ValueError):parse('{'+','.join('"k%d" "v"'%i for i in range(40))+'}')


@pytest.mark.asyncio
async def test_review_repairs_syntax_without_rejudging_or_changing_decision(monkeypatch):
    from agent.aigc import creation_review as review
    from agent.trace.store import TraceStore
    from tests.test_creation_review import request
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content='{"decision":"approve","reason" "方案一致","findings":[]}',usage={'input':5})))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    trace=TraceStore();result=await review.review_creation(request(),trace)
    assert result.decision=='approve' and result.reason=='方案一致'
    assert provider.chat.await_count==1 and result.tokens_used=={'input':5}
    events=[e for e in trace.get_run(result.run_id).events if e.type=='creation.review.syntax_repaired']
    assert len(events)==1 and events[0].payload=={'stage':'judge','inserted_colons':1}


@pytest.mark.asyncio
async def test_repaired_rejection_still_requires_real_candidate_evidence(monkeypatch):
    from agent.aigc import creation_review as review
    from agent.trace.store import TraceStore
    from tests.test_creation_review import request
    from tests.test_creation_review_geometry import asset
    req=request(assets=[dict(id=asset().id,name='图',mime_type='image/png',data_url=asset().data_url)],candidate_ids=[asset().id]);req.node_id='image'
    req.current_plan['nodes'].append(dict(id='image',kind='image',title='图',content='白兔',prompt='Draw a white rabbit'))
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content='{"decision":"revise","reason" "重画","findings":[]}')))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    with pytest.raises(ValueError,match='findings'):await review.review_creation(req,TraceStore())
    assert provider.chat.await_count==3
