import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.aigc import creation_planning as planning
from agent.llm.base import LLMResponse
from tests.test_creation_planning import plan, request
from tests.test_creation_scenes import multi_scene, with_scene


def repair_request(original):
    return request(current_plan=original, automatic_mode=True, require_video_scenes=True,
        locked_node_ids=['script', 'scene'],
        repair=dict(node_id='video', reason='缺少洞穴场景，请补齐对应场景图和时段', candidate_ids=[], attempt=1))


def test_video_repair_can_insert_only_necessary_scene_prerequisites():
    original = with_scene()
    revised = multi_scene()
    result = planning.parse_proposal(json.dumps(dict(reply='补齐场景', patch=dict(nodes=revised['nodes'][2:]))), repair_request(original))
    assert [n.id for n in result.plan.nodes] == ['script', 'scene', 'cave', 'video']
    assert result.plan.nodes[-1].references[-1].node_id == 'cave'
    assert original == with_scene()


@pytest.mark.parametrize('case', ['extra_video', 'unrelated_scene', 'changed_lock', 'reorder', 'removed', 'type'])
def test_scene_repair_still_preserves_delivery_locked_nodes_and_order(case):
    original, revised = with_scene(), multi_scene()
    if case == 'extra_video': revised['nodes'].append(dict(revised['nodes'][-1], id='extra'))
    if case == 'unrelated_scene': revised['nodes'].insert(2, dict(id='unrelated', kind='image', purpose='scene', title='other', prompt='other'))
    if case == 'changed_lock': revised['nodes'][0]['content'] = 'changed approved script'
    if case == 'reorder': revised['nodes'][1]['depends_on'] = []; revised['nodes'][:2] = reversed(revised['nodes'][:2])
    if case == 'removed': revised['nodes'] = revised['nodes'][:1]
    if case == 'type': revised['nodes'][-1] = dict(id='video', kind='image', title='changed output', prompt='image')
    with pytest.raises(ValueError):
        planning.parse_proposal(json.dumps(dict(reply='unsafe', plan=revised)), repair_request(original))


def test_type_specific_generation_contract_prevents_contradictory_fields():
    from agent.aigc.creation_contract import node_schema
    base = planning.RevisionResponse.model_json_schema()
    text = node_schema(base, 'text', patch=True, ident='script')
    assert text['properties']['references']['maxItems'] == 0
    assert text['properties']['storyboard'] == {'type': 'null'}
    assert text['properties']['asset_id']['enum'] == ['']
    image = node_schema(base, 'image', patch=True, ident='scene')
    assert image['properties']['references']['maxItems'] == 1
    video = node_schema(base, 'video', patch=True, ident='video')
    assert video['properties']['count']['enum'] == [1]
    refs = video['properties']['references']['items']['anyOf']
    for branch in refs:
        p = branch['properties']
        assert (p['node_id'].get('enum') == ['']) != (p['asset_id'].get('enum') == [''])
        if p['scene_intervals'].get('maxItems') != 0:
            assert p['role']['enum'] == ['reference'] and p['asset_id']['enum'] == ['']


@pytest.mark.asyncio
async def test_repeated_format_failure_repairs_one_node_and_keeps_valid_draft(monkeypatch):
    original = with_scene()
    draft = dict(reply='补场景', patch=dict(questions=[], nodes=multi_scene()['nodes'][2:]))
    draft['patch']['nodes'][-1]['references'][-1]['asset_id'] = 'rabbit'
    correction = dict(reply='仅修正视频引用', patch=dict(nodes=[dict(id='video', references=multi_scene()['nodes'][-1]['references'])]))
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(content=json.dumps(draft), model='initial-model'), LLMResponse(content=json.dumps(draft), model='initial-model'),
        LLMResponse(content=json.dumps(correction), model='recovery-model')]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    events = []
    async def report(event): events.append(event)
    result = await planning.propose_creation(repair_request(original), on_progress=report)
    assert [n.id for n in result.plan.nodes] == ['script', 'scene', 'cave', 'video']
    assert provider.chat.await_count == 3
    assert result.model_used == 'recovery-model'
    assert provider.chat.call_args.kwargs['tools'] is None
    assert any(e['stage'] == 'node_repair' and 'video' in e['message'] for e in events)
    assert original == with_scene()


@pytest.mark.asyncio
async def test_malformed_second_reply_cannot_discard_pending_valid_changes(monkeypatch):
    original = plan()
    draft = dict(reply='更新', patch=dict(questions=[], nodes=[
        dict(id='script', content='保留本轮有效修改', references=[dict(asset_id='rabbit', role='identity')])]))
    fixed = dict(reply='修正文本节点', patch=dict(nodes=[dict(id='script', references=[])]))
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(content=json.dumps(draft)),
        LLMResponse(content='{"reply":"broken",,"patch":{}}'), LLMResponse(content=json.dumps(fixed))]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    result = await planning.propose_creation(request(current_plan=original))
    assert result.plan.nodes[0].content == '保留本轮有效修改'
    assert not result.plan.nodes[0].references


@pytest.mark.asyncio
async def test_node_recovery_is_bounded_and_cannot_change_a_different_node(monkeypatch):
    original = with_scene()
    draft = dict(reply='补场景', patch=dict(nodes=multi_scene()['nodes'][2:]))
    draft['patch']['nodes'][-1]['references'][-1]['asset_id'] = 'rabbit'
    wrong = dict(reply='改脚本', patch=dict(nodes=[dict(id='script', content='overwrite')]))
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(content=json.dumps(draft)),
        LLMResponse(content=json.dumps(draft)), *[LLMResponse(content=json.dumps(wrong)) for _ in range(3)]]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    with pytest.raises(ValueError):
        await planning.propose_creation(repair_request(original))
    assert provider.chat.await_count <= 5 and original == with_scene()
