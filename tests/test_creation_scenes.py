import copy
import json

import pytest

from agent.aigc import creation_planning as planning
from tests.test_creation_planning import plan, request


def with_scene():
    value = plan('identity')
    value['nodes'].insert(1, dict(id='scene', kind='image', purpose='scene', title='竹林场景', prompt='Empty ink bamboo grove, wide establishing shot', depends_on=['script']))
    video = value['nodes'][-1]
    video['depends_on'].append('scene')
    video['references'].append(dict(node_id='scene', role='reference', note='Only the bamboo environment and light; no character identity'))
    video['storyboard']['subject_definitions'] += '\n<Picture 2> provides the bamboo environment.'
    video['storyboard']['retention_analysis'] += '\n<Picture 2> (appears in all shots): attribute_transfer - environment only.'
    return value


def parse(value, **kwargs):
    return planning.parse_proposal(json.dumps(dict(reply='请审阅', plan=value)), request(require_video_scenes=True, **kwargs))


def test_every_video_requires_its_own_scene_not_a_character_or_style_image():
    assert parse(with_scene()).plan.nodes[1].purpose == 'scene'
    with pytest.raises(ValueError, match='场景'):
        parse(plan('identity'))
    for change in ['purpose', 'role']:
        value = with_scene()
        if change == 'purpose': value['nodes'][1]['purpose'] = 'shot_reference'
        if change == 'role': value['nodes'][-1]['references'][-1]['role'] = 'style'
        if change == 'shared': value['nodes'].append({**copy.deepcopy(value['nodes'][-1]), 'id':'second_video'})
        with pytest.raises(ValueError, match='场景'):
            parse(value)


def test_scene_cannot_use_a_character_identity_or_conversion_template():
    value = with_scene()
    value['nodes'][1].update(references=[dict(asset_id='rabbit', role='identity')])
    with pytest.raises(ValueError, match='场景'):
        parse(value)


@pytest.mark.parametrize('role', ['environment', 'composition'])
def test_scene_can_recompose_an_existing_environment(role):
    value = with_scene()
    source = copy.deepcopy(value['nodes'][1])
    source.update(id='source_scene', title='已建立的环境')
    target = value['nodes'][1]
    target['depends_on'].append('source_scene')
    target['references'] = [dict(node_id='source_scene', role=role, note='只沿用环境结构，无人')]
    value['nodes'].insert(1, source)
    result = parse(value)
    assert result.plan.nodes[2].references[0].role == role
    assert result.plan.nodes[2].references[0].node_id == 'source_scene'


@pytest.mark.parametrize('role', ['environment', 'composition', 'reference', 'identity'])
def test_scene_cannot_import_unclassified_asset_pixels(role):
    value = with_scene()
    value['nodes'][1]['references'] = [dict(asset_id='rabbit', role=role)]
    with pytest.raises(ValueError, match='场景'):
        parse(value)


@pytest.mark.parametrize('purpose', ['character', 'key_visual', 'shot_reference'])
def test_scene_composition_source_must_itself_be_a_scene(purpose):
    value = with_scene()
    source = copy.deepcopy(value['nodes'][1])
    source.update(id='source', purpose=purpose)
    value['nodes'][1]['depends_on'].append('source')
    value['nodes'][1]['references'] = [dict(node_id='source', role='composition')]
    value['nodes'].insert(1, source)
    with pytest.raises(ValueError, match='场景'):
        parse(value)


def test_existing_confirmed_video_is_not_rewritten_to_add_scene():
    value = plan('identity')
    result = parse(value, current_plan=value, automatic_mode=True, locked_node_ids=['script','video'])
    assert result.plan.nodes[-1].references[0].asset_id == 'rabbit'


def test_scene_preflight_reports_all_missing_videos_in_one_repair():
    value=plan('identity')
    value['nodes'].append({**copy.deepcopy(value['nodes'][-1]), 'id':'second_video'})
    with pytest.raises(ValueError) as error:
        parse(value)
    assert '：video' in str(error.value) and '：second_video' in str(error.value)


def test_revision_inserts_new_scene_before_existing_video_without_reordering_other_nodes():
    original = plan('identity')
    revised = with_scene()
    req = request(current_plan=original, require_video_scenes=True)
    patch = dict(nodes=[revised['nodes'][1],dict(id='video',depends_on=revised['nodes'][-1]['depends_on'],references=revised['nodes'][-1]['references'],storyboard=revised['nodes'][-1]['storyboard'])])
    result = planning.parse_proposal(json.dumps(dict(reply='补充场景',patch=patch)),req)
    assert [n.id for n in result.plan.nodes] == ['script','scene','video']
    assert original == plan('identity')


def test_scene_revision_derives_dependency_from_explicit_image_reference():
    original = plan('identity')
    revised = with_scene()
    patch = dict(nodes=[revised['nodes'][1], dict(id='video', references=revised['nodes'][-1]['references'], storyboard=revised['nodes'][-1]['storyboard'])])
    result = planning.parse_proposal(json.dumps(dict(reply='补场景', patch=patch)), request(current_plan=original, require_video_scenes=True))
    assert result.plan.nodes[-1].depends_on == ['script', 'scene']
    assert [n.id for n in result.plan.nodes] == ['script', 'scene', 'video']
    assert original == plan('identity')
    # A misspelled/missing source cannot be guessed, and locked nodes aren't fixed silently.
    patch['nodes'][-1]['references'][-1]['node_id'] = 'missing_scene'
    with pytest.raises(ValueError, match='video.*missing_scene'):
        planning.parse_proposal(json.dumps(dict(reply='错误引用', patch=patch)), request(current_plan=original, require_video_scenes=True))
    patch['nodes'][-1]['references'][-1]['node_id'] = 'scene'
    with pytest.raises(ValueError, match='video.*scene'):
        planning.parse_proposal(json.dumps(dict(reply='锁定节点', patch=patch)), request(current_plan=original, require_video_scenes=True, locked_node_ids=['video']))


def test_added_scene_cycle_remains_invalid():
    original = plan('identity')
    revised = with_scene()
    revised['nodes'][1]['depends_on'] = ['other_scene']
    other = dict(id='other_scene', kind='image', purpose='scene', title='循环', prompt='empty forest', depends_on=['scene'])
    with pytest.raises(ValueError, match='循环'):
        planning.parse_proposal(json.dumps(dict(reply='错误循环', patch=dict(nodes=[revised['nodes'][1], other, revised['nodes'][-1]]))), request(current_plan=original, require_video_scenes=True))


def multi_scene():
    value=with_scene()
    other=copy.deepcopy(value['nodes'][1]);other.update(id='cave',title='洞穴',prompt='Wide empty glowing cave')
    value['nodes'].insert(2,other)
    video=value['nodes'][-1]
    video['depends_on'].append('cave')
    video['references'][-1]['scene_intervals']=[dict(start_seconds=0,end_seconds=2.5)]
    video['references'].append(dict(node_id='cave',role='reference',note='后半段飞入洞穴',scene_intervals=[dict(start_seconds=2.5,end_seconds=5)]))
    video['storyboard']['subject_definitions']+='\n<Picture 3> provides the cave environment.'
    video['storyboard']['retention_analysis']+='\n<Picture 3> (appears in all shots): attribute_transfer - environment only.'
    return value


def test_single_continuous_video_can_bind_two_scenes_and_compile_exact_execution_payload():
    from agent.aigc.video_prompting import compile_storyboard
    from agent.aigc.creation_scenes import SCENE_PREFIX
    result=parse(multi_scene())
    video=result.plan.nodes[-1]
    assert len(video.storyboard.shots)==1 and video.count==1
    assert '0-2.5s <Picture 2>' in video.prompt and '2.5-5s <Picture 3>' in video.prompt
    assert compile_storyboard(video.storyboard,planning.creative_video_request(video))==video.prompt
    # Round-trips are idempotent, including already confirmed videos.
    again=planning.parse_proposal(json.dumps(dict(reply='未改动',patch=dict(nodes=[]))),request(current_plan=result.plan.model_dump(),automatic_mode=True,locked_node_ids=[n.id for n in result.plan.nodes]))
    assert again.plan.nodes[-1].prompt==video.prompt
    assert again.plan.nodes[-1].storyboard.style.count(SCENE_PREFIX)==1


@pytest.mark.parametrize('case',['missing','gap','overlap','tail','overflow','identity','non_scene'])
def test_multiscene_binding_rejects_ambiguous_or_incomplete_environment_timeline(case):
    value=multi_scene();video=value['nodes'][-1]
    if case=='missing': video['references'][-1].pop('scene_intervals')
    if case=='gap': video['references'][-1]['scene_intervals'][0]['start_seconds']=3
    if case=='overlap': video['references'][-1]['scene_intervals'][0]['start_seconds']=2
    if case=='tail': video['references'][-1]['scene_intervals'][0]['end_seconds']=4
    if case=='overflow': video['references'][-1]['scene_intervals'][0]['end_seconds']=6
    if case=='identity': video['references'][0]['scene_intervals']=[dict(start_seconds=0,end_seconds=5)]
    if case=='non_scene': value['nodes'][2]['purpose']='shot_reference'
    with pytest.raises(ValueError,match='场景'):
        parse(value)


def test_same_environment_can_be_reused_across_multiple_videos():
    value=multi_scene()
    value['nodes'].append({**copy.deepcopy(value['nodes'][-1]),'id':'second_video'})
    assert len([n for n in parse(value).plan.nodes if n.kind=='video'])==2


def test_planning_catalogue_accepts_fifty_assets_but_bounds_image_previews():
    assets=[dict(id=f'a{i}',name=f'图{i}',mime_type='image/png',data_url='preview' if i<12 else '') for i in range(50)]
    req=planning.PlanningRequest(project_id='p',user_id='u',messages=[],assets=assets)
    assert len(req.assets)==50
    assets[12]['data_url']='extra'
    with pytest.raises(ValueError,match='预览'):
        planning.PlanningRequest(project_id='p',user_id='u',messages=[],assets=assets)
    with pytest.raises(ValueError,match='重复'):
        planning.PlanningRequest(project_id='p',user_id='u',messages=[],assets=[assets[0],assets[0]])


def test_expanded_canvas_accepts_64_nodes_and_rejects_65():
    value=dict(title='多集多场景',summary='完整目录',nodes=[dict(id=f'n{i}',kind='text',title='脚本',content='文本') for i in range(64)])
    assert len(planning.CreativePlan.model_validate(value).nodes)==64
    value['nodes'].append(dict(id='extra',kind='text',title='extra',content='text'))
    with pytest.raises(ValueError): planning.CreativePlan.model_validate(value)


@pytest.mark.asyncio
async def test_compaction_reserves_space_for_deterministic_scene_timeline():
    from tests.test_creation_compaction import editor
    from agent.aigc.creation_scenes import SCENE_PREFIX
    from unittest.mock import AsyncMock
    value=multi_scene()
    value['nodes'][-1]['storyboard']['style']='Watercolor forest with glowing cave. '*70
    value['nodes'][-1]['storyboard']['shots'][0]['description']='The rabbit flies from the forest into a glowing cave. '*40
    wire=json.dumps(dict(reply='分段游览',plan=value))
    compacted,_=await planning.compact_proposal(wire,request(require_video_scenes=True),editor(),AsyncMock())
    result=planning.parse_proposal(compacted,request(require_video_scenes=True))
    video=result.plan.nodes[-1]
    assert len(video.prompt)<=4000 and SCENE_PREFIX in video.prompt
    assert '2.5-5s <Picture 3>' in video.prompt


def test_confirmed_legacy_multiscene_video_is_preserved_without_forced_migration():
    value=multi_scene()
    for ref in value['nodes'][-1]['references']:
        ref.pop('scene_intervals',None)
    locked=[n['id'] for n in value['nodes']]
    result=parse(value,current_plan=value,automatic_mode=True,locked_node_ids=locked)
    assert len(result.plan.nodes[-1].references)==3
    assert all(not r.scene_intervals for r in result.plan.nodes[-1].references)
    with pytest.raises(ValueError,match='多场景'):
        parse(value)
