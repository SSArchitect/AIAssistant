import base64
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
import pytest
from agent.aigc.creation_review_geometry import Localizations, measured_geometry, review_preview, locate_subjects, approximate_scale_contract, scale_within_contract
from agent.llm.base import LLMResponse


def positions(**changes):
    return dict(images=[dict(candidate_id='candidate',uncertain=False,subjects=[dict(
        label='远处白兔',body=dict(left=550,top=310,right=590,bottom=336),
        ridden_prop=dict(left=540,top=335,right=600,bottom=340))])],**changes)


def test_scale_comes_from_box_geometry_not_a_verbal_estimate():
    result=measured_geometry(Localizations.model_validate(positions()))[0]
    assert result['subjects'][0]['body_height_percent']==2.6
    assert result['subjects'][0]['body_and_prop_height_percent']==3.0
    assert result['subject_count']==1 and not result['uncertain']


def test_invalid_or_inverted_localization_is_rejected():
    value=positions();value['images'][0]['subjects'][0]['body']['bottom']=300
    with pytest.raises(ValueError):Localizations.model_validate(value)


def test_approximate_scale_has_stable_bounds_without_relaxing_exact_limits():
    contract=approximate_scale_contract('御剑远景，整体高度严格约为画高3%（在1024像素高画面中约30像素）')
    assert contract['minimum_percent']==2.4 and contract['maximum_percent']==3.6
    assert scale_within_contract(contract,measured_geometry(Localizations.model_validate(positions())),'candidate') is True
    for text in ['人物最多占画高3%','人物精确占画高3%','人物约占画高3%，蘑菇约占画高20%']:
        assert approximate_scale_contract(text) is None
    value=positions();value['images'][0]['uncertain']=True
    assert scale_within_contract(contract,measured_geometry(Localizations.model_validate(value)),'candidate') is None


def test_confirmed_in_range_scale_cannot_trigger_repainting_but_large_subject_can():
    from agent.aigc.creation_review import ReviewDecision
    from agent.aigc.creation_review_evidence import validate_image_findings
    requirement='御剑远景，人物约占画高3%'
    contract=approximate_scale_contract(requirement)
    decision=ReviewDecision(decision='revise',reason='大小不符',findings=[dict(candidate_id='candidate',category='scale',
        source_id='target',requirement_quote='人物约占画高3%',observation='角色只有2.5%，未达到3%')])
    with pytest.raises(ValueError,match='审阅区间'):
        validate_image_findings(decision,['candidate'],{'target':requirement},scale_contract=contract,
            geometry=measured_geometry(Localizations.model_validate(positions())))
    large=positions();large['images'][0]['subjects'][0]['body']['bottom']=500
    decision.findings[0].observation='角色高度占画高19%，明显超过约3%'
    validate_image_findings(decision,['candidate'],{'target':requirement},scale_contract=contract,
        geometry=measured_geometry(Localizations.model_validate(large)))


def test_scale_ambiguity_does_not_suppress_a_rejection_or_relax_other_composition():
    from agent.aigc.creation_review import ReviewDecision
    from agent.aigc.creation_review_evidence import validate_image_findings
    requirement='人物约占画高3%，位于画面上方'
    contract=approximate_scale_contract(requirement)
    decision=ReviewDecision(decision='revise',reason='位置不符',findings=[dict(candidate_id='candidate',category='composition',
        source_id='target',requirement_quote='位于画面上方',observation='人物位于底部')])
    geometry=measured_geometry(Localizations.model_validate(positions()))
    validate_image_findings(decision,['candidate'],{'target':requirement},scale_contract=contract,geometry=geometry)
    for count in [0,2]:
        item={**geometry[0],'subject_count':count}
        assert scale_within_contract(contract,[item],'candidate') is None
    assert scale_within_contract(contract,[],'candidate') is None
    decision.findings[0].observation='人物身高占画高2.5%未达到3%'
    with pytest.raises(ValueError,match='scale分类'):
        validate_image_findings(decision,['candidate'],{'target':requirement},scale_contract=contract,geometry=geometry)


def asset(width=576,height=1024):
    data=BytesIO();Image.new('RGB',(width,height),'white').save(data,format='PNG')
    return SimpleNamespace(id='candidate',name='User wants 3 percent',
        data_url='data:image/png;base64,'+base64.b64encode(data.getvalue()).decode())


def test_visual_review_retains_native_detail_and_caps_large_images():
    for size,expected in [((576,1024),(576,1024)),((2048,4096),(768,1536))]:
        value=review_preview(asset(*size).data_url)
        with Image.open(BytesIO(base64.b64decode(value.split(',')[1]))) as image:
            assert image.size==expected


@pytest.mark.asyncio
async def test_localization_is_goal_blind_and_recovers_missing_candidate():
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(content=json.dumps(positions()).replace('candidate','foreign')),
        LLMResponse(content=json.dumps(positions()),usage={'output':12})]))
    result,usage=await locate_subjects(provider,[asset()],['candidate'])
    assert result[0]['subjects'][0]['body_height_percent']==2.6
    assert usage['output']==12 and provider.chat.await_count==2
    dialogue=provider.chat.call_args.args[0]
    assert 'User wants' not in str(dialogue) and '3 percent' not in str(dialogue)
    assert any(part['type']=='image_url' for part in dialogue[1].content)
