import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.aigc.creation_review import ReviewDecision
from agent.aigc.creation_review_evidence import ReviewEvidenceError, validate_image_findings
from agent.llm.base import LLMResponse


def finding(source='target', category='composition'):
    return dict(candidate_id='draft', category=category, source_id=source,
        requirement_quote='悬停在巨树前下方', observation='人物偏左，没有位于巨树中轴线上')


def test_identity_reference_cannot_authorize_position_or_pose_requirements():
    source='reference:hero:identity'
    for category in ('action','composition','scale','environment'):
        decision=ReviewDecision(decision='revise',reason='不合格',findings=[finding(source,category)])
        with pytest.raises(ReviewEvidenceError,match='身份参考'):
            validate_image_findings(decision,['draft'],{source:'保持身份、服装和道具特征'})


@pytest.mark.asyncio
@pytest.mark.parametrize('supported',[False,True])
async def test_text_only_criteria_check_cannot_turn_rejection_into_approval(supported):
    from agent.aigc.creation_review_criteria import check_rejection_criteria
    decision=ReviewDecision(decision='revise',reason='重画',findings=[finding()])
    before=decision.model_dump();usage={}
    response=dict(checks=[dict(finding_index=0,supported=supported,reason='前下方没有要求必须居中')])
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(response),usage={'input':12})))
    if supported:
        await check_rejection_criteria(provider,decision.findings,{'target':'悬停在巨树前下方'},usage)
    else:
        with pytest.raises(ReviewEvidenceError,match='未被引用要求支持'):
            await check_rejection_criteria(provider,decision.findings,{'target':'悬停在巨树前下方'},usage)
    assert decision.model_dump()==before and usage=={'input':12}
    messages=provider.chat.call_args.args[0]
    assert all(isinstance(m.content,str) for m in messages)
    payload=json.loads(messages[1].content)
    assert payload['sources']=={'target':'悬停在巨树前下方'}
    assert 'candidate_id' not in payload['findings'][0]


@pytest.mark.asyncio
@pytest.mark.parametrize('checks',[[],[dict(finding_index=1,supported=True,reason='yes')],
    [dict(finding_index=0,supported=True,reason='yes')]*2])
async def test_criteria_check_requires_complete_unique_coverage(checks):
    from agent.aigc.creation_review_criteria import check_rejection_criteria
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(checks=checks)))))
    decision=ReviewDecision(decision='revise',reason='重画',findings=[finding()])
    with pytest.raises(ReviewEvidenceError):
        await check_rejection_criteria(provider,decision.findings,{'target':'悬停在巨树前下方'},{})


@pytest.mark.asyncio
@pytest.mark.parametrize('corrected',['select','revise'])
async def test_unsupported_criterion_returns_to_visual_judge_and_preserves_real_defects(monkeypatch,corrected):
    from agent.aigc import creation_review as review
    from tests.test_creation_review import request
    import base64
    from io import BytesIO
    from PIL import Image
    image=BytesIO();Image.new('RGB',(8,8),'red').save(image,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(image.getvalue()).decode()
    req=request(assets=[dict(id='draft',name='图',mime_type='image/png',data_url=data)],candidate_ids=['draft'])
    req.current_plan['nodes'].append(dict(id='image',kind='image',purpose='shot_reference',title='远景',
        content='悬停在巨树前下方，保持白兔身份',prompt='Generate'))
    req.node_id='image';before=req.model_dump()
    rejected=LLMResponse(content=json.dumps(dict(decision='revise',reason='不居中',findings=[finding()])))
    decision=dict(decision=corrected,asset_id='draft' if corrected=='select' else '',reason='重新对照像素',findings=[])
    if corrected=='revise':
        decision['findings']=[{**finding(category='identity'),'requirement_quote':'保持白兔身份','observation':'候选是黑猫'}]
    responses=[rejected,rejected,
        LLMResponse(content=json.dumps(dict(checks=[dict(finding_index=0,supported=False,reason='原文没有要求居中')]))),
        LLMResponse(content=json.dumps(decision))]
    if corrected=='revise':responses.append(LLMResponse(content=json.dumps(dict(checks=[dict(finding_index=0,supported=True,reason='明确要求白兔')]))))
    provider=SimpleNamespace(chat=AsyncMock(side_effect=responses))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(req)
    assert result.decision==corrected and req.model_dump()==before
    assert provider.chat.await_count==(4 if corrected=='select' else 5)
    corrected_request=provider.chat.call_args_list[3].args[0]
    assert '未被引用要求支持' in corrected_request[-1].content
    assert any(p['type']=='image_url' for p in corrected_request[1].content)
    if corrected=='revise':assert result.findings[0].category=='identity'


@pytest.mark.asyncio
async def test_criteria_timeout_never_silently_allows_redraw():
    import asyncio
    from agent.aigc.creation_review_criteria import check_rejection_criteria
    provider=SimpleNamespace(chat=AsyncMock(side_effect=asyncio.TimeoutError))
    decision=ReviewDecision(decision='revise',reason='重画',findings=[finding()])
    with pytest.raises(ReviewEvidenceError,match='不能直接据此重画'):
        await check_rejection_criteria(provider,decision.findings,{'target':'悬停在巨树前下方'},{})
