import copy,json
import pytest
from agent.aigc import creation_planning as p
from tests.test_creation_scenes import with_scene,parse
from tests.test_creation_planning import request


def with_shot():
    value=with_scene()
    shot=dict(id='shot_frame',kind='image',purpose='shot_reference',title='兔大侠御剑',prompt='Rabbit flies over the grove',depends_on=['script','scene'],references=[dict(asset_id='rabbit',role='identity',note='兔大侠'),dict(node_id='scene',role='environment',note='竹林')])
    value['nodes'].insert(2,shot)
    video=value['nodes'][-1];video['shot_ids']=['fly_in'];video['depends_on'].append('shot_frame')
    video['references'].append(dict(node_id='shot_frame',role='reference',shot_ids=['fly_in'],note='composition'))
    video['storyboard']['subject_definitions']+='\n<Picture 3> provides the shot composition.'
    video['storyboard']['retention_analysis']+='\n<Picture 3> (appears in all shots): weak_reference - composition only.'
    return value


def test_shot_reference_uses_two_sources_and_compiles_stable_binding():
    result=parse(with_shot())
    image=result.plan.nodes[2];video=result.plan.nodes[-1]
    assert len(image.references)==2 and image.references[1].role=='environment'
    assert 'fly_in' in video.prompt and '<Picture 3>' in video.prompt and '[Shot 1]' in video.prompt
    again=p.parse_proposal(json.dumps(dict(reply='unchanged',patch=dict(nodes=[]))),request(current_plan=result.plan.model_dump()))
    assert again.plan.nodes[-1].prompt==video.prompt


@pytest.mark.parametrize('case',['unknown','duplicate','missing_ids','wrong_source','image_scope','too_many','conversion'])
def test_invalid_shot_bindings_and_image_inputs_fail_locally(case):
    value=with_shot();video=value['nodes'][-1];image=value['nodes'][2]
    if case=='unknown':video['references'][-1]['shot_ids']=['another_shot']
    if case=='duplicate':video['shot_ids']=['fly_in','fly_in']
    if case=='missing_ids':video['references'][-1]['shot_ids']=[]
    if case=='wrong_source':video['references'][0]['shot_ids']=['fly_in']
    if case=='image_scope':image['references'][0]['shot_ids']=['fly_in']
    if case=='too_many':image['references'] += [dict(asset_id='a',role='identity'),dict(asset_id='b',role='identity')]
    if case=='conversion':image['character_style']='chibi'
    with pytest.raises(ValueError):parse(value)


def test_reordering_shots_keeps_reference_on_stable_id():
    value=with_shot();video=value['nodes'][-1]
    second=copy.deepcopy(video['storyboard']['shots'][0]);second['start_seconds']=2.5
    video['storyboard']['shots'].append(second);video['shot_ids']=['establish','fly_in']
    result=parse(value)
    assert 'fly_in' in result.plan.nodes[-1].prompt and '<Picture 3> -> [Shot 2]' in result.plan.nodes[-1].prompt


@pytest.mark.asyncio
async def test_inconsistent_shot_ids_do_not_crash_before_planning_validation():
    from unittest.mock import AsyncMock
    value=with_shot();video=value['nodes'][-1]
    video['shot_ids']=['opening','fly_in']  # Only one structured shot exists.
    wire=json.dumps(dict(reply='补齐分镜绑定',plan=value))
    before=copy.deepcopy(value)
    content,usage=await p.compact_proposal(wire,request(),None,AsyncMock())
    with pytest.raises(ValueError,match='镜头ID'):
        p.parse_proposal(content,request())
    assert value==before and usage=={}


def test_shot_binding_compiler_rejects_mismatched_arrays_without_index_error():
    from types import SimpleNamespace
    from agent.aigc.creation_shots import shot_reference_rule
    node=SimpleNamespace(id='video',shot_ids=['one','two'],storyboard=SimpleNamespace(shots=[SimpleNamespace(start_seconds=0)]),
        references=[SimpleNamespace(shot_ids=['two'])],duration_seconds=5)
    with pytest.raises(ValueError,match='镜头ID'):shot_reference_rule(node)


def test_generation_schema_allows_three_image_inputs_but_no_image_shot_scope():
    from agent.aigc.creation_contract import planning_schema
    schema=planning_schema(p.PlanningResponse,request())
    image=next(n for n in schema['$defs']['CreativePlan']['properties']['nodes']['items']['anyOf'] if n['properties']['kind']['enum']==['image'])
    assert image['properties']['references']['maxItems']==3
    assert image['properties']['shot_ids']['maxItems']==0


def test_new_video_contract_requires_shot_images_but_legacy_approved_video_is_preserved():
    with pytest.raises(ValueError, match='关键分镜'):
        parse(with_scene(),require_shot_references=True)
    original=parse(with_scene()).plan.model_dump()
    result=p.parse_proposal(json.dumps(dict(reply='保留已确认',patch=dict(nodes=[]))),request(current_plan=original,require_shot_references=True,automatic_mode=True,locked_node_ids=['script','scene','video']))
    assert result.plan.model_dump()==original
    assert parse(with_shot(),require_shot_references=True).plan.nodes[-1].shot_ids==['fly_in']


def test_repair_can_add_linked_character_and_shot_without_changing_locked_scene():
    from tests.test_creation_repair_protocol import repair_request
    original=with_scene()
    revised=with_shot()
    character=dict(id='new_character',kind='image',purpose='character',title='兔大侠人设',prompt='white rabbit swordsman')
    revised['nodes'].insert(2,character)
    shot=revised['nodes'][3];shot['references'][0]=dict(node_id='new_character',role='identity');shot['depends_on'].append('new_character')
    result=p.parse_proposal(json.dumps(dict(reply='补人设和分镜',patch=dict(nodes=revised['nodes'][2:]))),repair_request(original))
    assert [n.id for n in result.plan.nodes]==['script','scene','new_character','shot_frame','video']
    assert result.plan.nodes[1].prompt==original['nodes'][1]['prompt']
    revised['nodes'].insert(2,dict(character,id='unrelated'))
    with pytest.raises(ValueError,match='无关'):
        p.parse_proposal(json.dumps(dict(reply='错误',patch=dict(nodes=revised['nodes'][2:]))),repair_request(original))
