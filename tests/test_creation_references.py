import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.aigc.creation_planning import compact_proposal, parse_proposal, PlanningRequest
from agent.aigc.creation_references import ReferenceRepair, apply_reference_repair, repair_reference_storyboard
from agent.aigc.creation_models import PlanningConstraintError, planning_error
from agent.aigc.video_prompting import VideoStoryboard, compile_storyboard
from agent.schemas.aigc import VideoGenerationRequest
from agent.llm.base import LLMResponse


def board():
    return VideoStoryboard(style='Ink.', shots=[dict(start_seconds=0., description='<Subject 1> bows using <Picture 2>. <d>[Chinese]你好。</d>',
        panels=[dict(start_seconds=0.,end_seconds=5.,description='The rabbit smiles.')])], overall_soundscape='Wind.',
        subject_definitions='<Subject 1> is the rabbit from <Picture 2>.',summary='[reference generation] A rabbit bows.',
        retention_analysis='<Subject 1> (appears in [Shot 1]): fully_preserved - identity.')


def correction():
    return dict(labels=[dict(kind='Picture',source=2,target=1)],
        subject_definitions='<Subject 1> is the rabbit from <Picture 1>.',
        summary='[reference generation] A rabbit bows.',
        retention_analysis='<Subject 1> (appears in [Shot 1]): fully_preserved - identity.')


def blueprint_correction():
    return dict(labels=[dict(kind='Picture',source=2,target=1)], summary='A rabbit bows.', entries=[dict(
        kind='Subject',number=1,description='is the rabbit',pictures=[1],shots=[1],retention='fully_preserved',retained_features='identity.')])


@pytest.mark.asyncio
async def test_node_reference_repair_corrects_global_picture_index_without_rewriting_shots():
    source=board(); before=source.model_dump()
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(blueprint_correction()),usage={'output_tokens':20})))
    req=VideoGenerationRequest(prompt='placeholder',duration_seconds=5,reference_image_data_urls=['data:image/png;base64,eA=='])
    images=[dict(picture=1,source='rabbit',name='兔大侠人设',role='identity',note='仅锁定兔子身份')]
    fixed,usage=await repair_reference_storyboard(source,req,images,provider)
    assert '<Picture 2>' not in compile_storyboard(fixed,req)
    assert fixed.shots[0].panels==source.shots[0].panels
    assert fixed.shots[0].description==source.shots[0].description.replace('<Picture 2>','<Picture 1>')
    assert source.model_dump()==before and usage=={'output_tokens':20}
    assert json.loads(provider.chat.call_args.args[0][1].content)['input_images']==images


@pytest.mark.asyncio
async def test_multiple_nodes_receive_independent_reference_repairs_and_keep_selected_questions_resolved():
    prior=dict(title='故事',summary='动画',nodes=[dict(id='script',kind='text',purpose='script',title='脚本',content='已审阅原稿')],
        questions=[dict(question='交付方式？',options=['三段','一段'])])
    nodes=[dict(id=f'video{i}',kind='video',title=f'片段{i}',depends_on=['script'],references=[dict(asset_id='rabbit',role='identity',note='兔子身份')],storyboard=board().model_dump()) for i in range(3)]
    wire=json.dumps(dict(reply='按你的选择规划三段',patch=dict(nodes=nodes,questions=[])))
    request=PlanningRequest(project_id='p',user_id='u',messages=[],current_plan=prior,assets=[dict(id='rabbit',name='人设',mime_type='image/png')])
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(blueprint_correction()))))
    result,_=await compact_proposal(wire,request,provider,AsyncMock())
    parsed=parse_proposal(result,request)
    assert len(parsed.plan.nodes)==4 and parsed.plan.questions==[]
    assert parsed.plan.nodes[0].content=='已审阅原稿'
    assert provider.chat.await_count==3
    assert prior['questions'] and len(prior['nodes'])==1


@pytest.mark.asyncio
async def test_reference_repair_is_bounded_and_rejects_missing_input_roles():
    req=VideoGenerationRequest(prompt='placeholder',duration_seconds=5,reference_image_data_urls=['data:image/png;base64,eA==','data:image/png;base64,eQ=='])
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(blueprint_correction()))))
    with pytest.raises(PlanningConstraintError) as caught:
        await repair_reference_storyboard(board(),req,[],provider)
    assert provider.chat.await_count==3
    assert planning_error(caught.value)[0]=='video_reference_failed'


def test_reference_repair_cannot_change_dialogue_timing_or_map_a_label_twice():
    value=correction();value['summary']+='<d>[Chinese]新增台词</d>'
    with pytest.raises(ValueError,match='对白'):
        apply_reference_repair(board(),ReferenceRepair(**value))
    value=correction();value['labels']*=2
    with pytest.raises(ValueError,match='只能映射一次'):
        apply_reference_repair(board(),ReferenceRepair(**value))
    value=correction();value['shots']=[]
    with pytest.raises(ValueError):ReferenceRepair(**value)


def test_reference_blueprint_compiles_three_environments_in_one_continuous_shot():
    from agent.aigc.creation_references import ReferenceBlueprint
    value=dict(labels=[],summary='Travel forest to cave to island.',entries=[dict(kind='Picture',number=i,
        description=f'provides environment {i}',pictures=[i],shots=[1],retention='attribute_transfer',retained_features='environment only') for i in range(1,4)])
    repair=ReferenceBlueprint.model_validate(value).materialize(3,1,'reference_to_video')
    source=VideoStoryboard(style='Watercolor.',shots=[dict(start_seconds=0.,description='Continuous flying camera.')],overall_soundscape='Wind.')
    fixed=apply_reference_repair(source,repair)
    req=VideoGenerationRequest(prompt='placeholder',duration_seconds=15,reference_image_data_urls=['data:image/png;base64,eA==','data:image/png;base64,eQ==','data:image/png;base64,eg=='])
    rendered=compile_storyboard(fixed,req)
    assert '[Shot 2]' not in rendered and '[reference generation]' in rendered
    assert len(repair.subject_definitions.splitlines())==3
    assert fixed.shots==source.shots
    value['entries'][1]['shots']=[2]
    with pytest.raises(ValueError,match='Logical Shot'):
        ReferenceBlueprint.model_validate(value).materialize(3,1,'reference_to_video')
    value['entries'][1]['shots']=[1];value['entries'][1]['pictures']=[1]
    with pytest.raises(ValueError,match='同号'):
        ReferenceBlueprint.model_validate(value).materialize(3,1,'reference_to_video')


@pytest.mark.asyncio
async def test_reference_repair_constraints_use_actual_shots_not_scene_count():
    good=blueprint_correction()
    wrong=json.loads(json.dumps(good));wrong['entries'][0]['shots']=[2]
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(content=json.dumps(wrong)),LLMResponse(content=json.dumps(good))]))
    req=VideoGenerationRequest(prompt='placeholder',duration_seconds=5,reference_image_data_urls=['data:image/png;base64,eA=='])
    result,_=await repair_reference_storyboard(board(),req,[dict(picture=1,role='identity')],provider)
    assert provider.chat.await_count==2 and '[Shot 2]' not in result.retention_analysis
    system=provider.chat.call_args.args[0][0].content
    schema=json.loads(system.split('JSON schema:\n')[1])
    assert schema['$defs']['ReferenceEntry']['properties']['shots']['items']['enum']==[1]
    assert json.loads(provider.chat.call_args.args[0][1].content)['actual_shots']==[dict(number=1,start_seconds=0.)]
