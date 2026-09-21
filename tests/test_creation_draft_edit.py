"""A rejected draft is editable input, never an approved identity or output."""
import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from agent.aigc import creation, creation_media_state, creation_planning as planning
from agent.config import runtime_config
from agent.llm.base import LLMResponse
from tests.test_creation import PNG, request as media_request
from tests.test_creation_planning import plan, request


def editing_request():
    value = plan()
    value['nodes'].insert(1, dict(id='frame', kind='image', title='远景', purpose='shot_reference',
        content='人物约占画高10%，脚踩飞剑。', prompt='Small rider in a wide forest',
        references=[dict(asset_id='rabbit', role='identity')]))
    req = request(current_plan=value, automatic_mode=True, locked_node_ids=['script', 'video'],
        repair=dict(node_id='frame', reason='人物过大', candidate_ids=['draft'], attempt=3,
            findings=[dict(candidate_id='draft', category='scale', source_id='target',
                requirement_quote='人物约占画高10%', observation='当前占画高25%')]))
    req.assets.append(planning.PlanningAsset(id='draft', name='待修图.png', mime_type='image/png'))
    return req


def patch(**changes):
    return json.dumps(dict(reply='局部修改后重新审阅', patch=dict(nodes=[dict(id='frame', **changes)])))


@pytest.mark.asyncio
async def test_repair_can_edit_own_candidate_without_promoting_it_to_reference(monkeypatch):
    req = editing_request(); before = copy.deepcopy(req.model_dump())
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=patch(
        edit_source_asset_id='draft', prompt='Reduce only the rider, preserve the scene'))))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    result = await planning.propose_creation(req)
    node = result.plan.nodes[1]
    assert node.edit_source_asset_id == 'draft' and node.asset_id == ''
    assert [r.asset_id for r in node.references] == ['rabbit']
    assert node.content == req.current_plan['nodes'][1]['content']
    assert req.model_dump() == before
    assert 'edit_source_asset_id' in provider.chat.call_args.args[0][0].content


@pytest.mark.parametrize('case', ['foreign', 'other_node', 'new_node', 'unseen', 'locked', 'identity_change'])
def test_edit_source_must_be_current_node_candidate_with_stable_reference_context(case):
    req = editing_request(); changes = dict(edit_source_asset_id='draft', prompt='Edit this draft')
    if case == 'foreign': changes['edit_source_asset_id'] = 'other-account'
    if case == 'other_node': req.repair.node_id = 'video'
    if case == 'new_node': req.current_plan['nodes'].pop(1)
    if case == 'unseen': req.repair.candidate_ids = []
    if case == 'locked': req.locked_node_ids.append('frame')
    if case == 'identity_change': changes['references'] = []
    with pytest.raises(ValueError): planning.parse_proposal(patch(**changes), req)


def test_rejected_candidate_remains_forbidden_as_approved_asset_or_identity():
    req = editing_request()
    for changes in [dict(asset_id='draft', references=[]), dict(references=[dict(asset_id='draft', role='identity')])]:
        with pytest.raises(ValueError): planning.parse_proposal(patch(**changes), req)


def test_existing_edit_can_be_retained_or_explicitly_cleared_for_regeneration():
    req = editing_request()
    result = planning.parse_proposal(patch(edit_source_asset_id='draft', prompt='Shrink rider'), req)
    req.current_plan = result.plan.model_dump()
    req.repair = None; req.automatic_mode = False
    retained = planning.parse_proposal(patch(title='新标题'), req).plan.nodes[1]
    assert retained.edit_source_asset_id == 'draft'
    regenerated = planning.parse_proposal(patch(edit_source_asset_id='', prompt='Generate a wide forest'), req).plan.nodes[1]
    assert regenerated.edit_source_asset_id == ''


def test_edit_cannot_silently_retain_pixels_when_upstream_requirements_change():
    from agent.aigc.creation_draft_edit import validate_edit_sources
    req = editing_request()
    req.current_plan['nodes'][1]['depends_on'] = ['script']
    proposed = planning.CreativePlan.model_validate(req.current_plan)
    proposed.nodes[1].edit_source_asset_id = 'draft'
    proposed.nodes[0].content = 'A completely different scene'
    with pytest.raises(ValueError, match='上游'):
        validate_edit_sources(proposed, req)


@pytest.mark.parametrize('case', ['video', 'text', 'adopt', 'stylize', 'no_requirements'])
def test_invalid_edit_combinations_are_rejected(case):
    node = dict(id='n', kind='image', title='n', content='Original creative requirement', prompt='Edit', edit_source_asset_id='draft')
    if case in ('video', 'text'): node['kind'] = case
    if case == 'adopt': node['asset_id'] = 'draft'
    if case == 'stylize': node['character_style'] = 'anime'
    if case == 'no_requirements': node['content'] = ''
    with pytest.raises(ValueError): planning.CreativeNode.model_validate(node)


@pytest.mark.asyncio
async def test_edit_execution_preserves_draft_pixels_skips_reference_reinterpretation_and_resumes(monkeypatch, tmp_path):
    from agent.aigc import creation_reference_images as refs
    monkeypatch.setattr(creation_media_state, 'STATE_DIR', tmp_path)
    prepare = AsyncMock(side_effect=AssertionError('draft cannot become a new-canvas reference'))
    monkeypatch.setattr(refs, 'prepare_reference_image', prepare)
    generate = AsyncMock(return_value=SimpleNamespace(id='edited', images=[SimpleNamespace(base64=PNG.split(',')[1], mime_type='image/png')]))
    monkeypatch.setattr(creation, 'generate_image', generate)
    req = media_request(image_operation='edit', image_purpose='shot_reference', input_images=[PNG])
    await creation.execute_node(req)
    sent = generate.call_args.args[0]
    assert sent.mode == 'reference_to_image' and sent.reference_image_data_urls == [PNG]
    assert sent.prompt == req.prompt and not prepare.called
    await creation.execute_node(req.model_copy(update={'resume_task_id':'edited'}))
    assert generate.call_args.kwargs == {'resume_task_id':'edited'}
    assert not prepare.called


@pytest.mark.parametrize('options', [dict(input_images=[]), dict(input_images=[PNG], character_style='anime'),
    dict(input_images=[PNG], image_references=[dict(role='identity')])])
def test_media_edit_requires_one_draft_and_no_reference_or_stylization(options):
    with pytest.raises(ValidationError): media_request(image_operation='edit', **options)


def test_new_operation_field_does_not_invalidate_accepted_legacy_task(monkeypatch, tmp_path):
    monkeypatch.setattr(creation_media_state, 'STATE_DIR', tmp_path)
    req = media_request(input_images=[PNG])
    old = req.model_dump_json(exclude={'resume_task_id', 'image_operation'})
    fingerprint = hashlib.sha256((old+'\n'+runtime_config.get('aigc.spark.base_url')).encode()).hexdigest()
    path = tmp_path / (hashlib.sha256(req.idempotency_key.encode()).hexdigest()+'.json')
    path.write_text(json.dumps(dict(fingerprint=fingerprint, task_id='old-job', stage='running')))
    assert creation_media_state.CreationMediaState(req).task_id == 'old-job'
    with pytest.raises(ValueError, match='上下文已变化'):
        creation_media_state.CreationMediaState(req.model_copy(update={'image_operation':'edit'}))


def test_reviewer_receives_new_candidate_and_original_requirements_without_draft_authority():
    from agent.aigc.creation_review import ReviewRequest, review_context
    req = editing_request()
    proposed = planning.parse_proposal(patch(edit_source_asset_id='draft', prompt='Shrink and preserve existing pixels'), req).plan
    review = ReviewRequest(**{**req.model_dump(), 'current_plan': proposed.model_dump(), 'repair': None},
        node_id='frame', candidate_ids=['edited'])
    review.assets.append(planning.PlanningAsset(id='edited', name='新候选.png', mime_type='image/png'))
    parts = review_context(review, proposed, proposed.nodes[1])
    payload = json.loads(parts[0]['text'])
    assert payload['review_target']['content'] == req.current_plan['nodes'][1]['content']
    assert payload['review_target']['prompt'] == ''
    assert 'edit_source_asset_id' not in payload['review_target']
    assert {a['id'] for a in payload['assets']} == {'rabbit', 'edited'}
