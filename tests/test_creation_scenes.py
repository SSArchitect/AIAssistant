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
    for change in ['purpose', 'role', 'shared']:
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
