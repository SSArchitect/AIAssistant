"""Regression: large reference portraits must not force a full-frame redraw."""
import base64
import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
from PIL import Image
import pytest

from agent.aigc import creation, creation_image_layout as layout, creation_media_state as state
from agent.aigc.creation_planning import CreativeNode
from agent.config import runtime_config
from agent.aigc.progress import emit_progress
from agent.aigc.spark_client import SparkProviderError

PLACEMENT = dict(center_x_percent=25.5, center_y_percent=82.6, subject_height_percent=10, subject_prompt='One rear three-quarter rabbit looking up, both feet on its carrot sword.')

def data(image):
    return 'data:image/png;base64,' + base64.b64encode(layout.png_bytes(image)).decode()


def request(**changes):
    values = dict(kind='image', prompt='Wide forest, small rider', image_purpose='shot_reference', aspect_ratio='9:16',
        image_layout=[PLACEMENT], image_references=[dict(role='environment'), dict(role='identity')],
        input_images=[data(Image.new('RGB', (576,1024), '#726652')), data(Image.new('RGB',(512,512),'white'))],
        idempotency_key='region-original')
    return creation.CreationNodeRequest(**{**values, **changes})


def test_real_small_subject_box_and_overflow_validation():
    p=layout.ImagePlacement(**PLACEMENT)
    assert layout.region_box(p,'9:16') == (77,776,217,916)
    with pytest.raises(ValueError,match='超出画幅'):
        request(image_layout=[{**PLACEMENT,'center_x_percent':0}])


@pytest.mark.parametrize('changes', [dict(kind='video'),dict(image_purpose='scene'),dict(image_operation='edit'),dict(character_style='chibi'),
    dict(image_references=[dict(role='identity'),dict(role='identity')]),dict(image_layout=[PLACEMENT,PLACEMENT]),
    dict(image_layout=[{**PLACEMENT,'subject_height_percent':float('nan')}]),dict(image_layout=[{**PLACEMENT,'subject_prompt':' '}])])
def test_invalid_modes_roles_and_nonfinite_parameters_fail_before_submission(changes):
    with pytest.raises(ValueError): request(**changes)


@pytest.mark.asyncio
async def test_region_execution_saves_full_frame_preserving_outside_and_task_identity(monkeypatch):
    req=request()
    isolate=AsyncMock(side_effect=lambda image,*args:image)
    monkeypatch.setattr(layout,'isolated_identity_view',isolate)
    patch=Image.new('RGB',(512,512),'#b5a78f')
    for y in range(200,312):
        for x in range(200,312):patch.putpixel((x,y),(0,0,0))
    async def generate(sent,**kwargs):
        assert not kwargs and sent.idempotency_key==req.idempotency_key
        assert sent.width==sent.height==512 and sent.aspect_ratio=='1:1'
        assert sent.mode=='reference_to_image' and sent.reference_image_data_urls[1]==req.input_images[1]
        assert '74 percent' in sent.prompt and PLACEMENT['subject_prompt'] in sent.prompt
        assert '10%' not in sent.prompt
        return SimpleNamespace(id='real-provider-patch',images=[SimpleNamespace(base64=base64.b64encode(layout.png_bytes(patch)).decode(),mime_type='image/png')])
    monkeypatch.setattr(creation,'generate_image',generate)
    result=await creation._execute_node(req)
    final=Image.open(BytesIO(base64.b64decode(result['content'])))
    assert final.size==(576,1024) and result['provider_task_id']=='real-provider-patch'
    before=np.asarray(layout.read_image(req.input_images[0])); after=np.asarray(final)
    outside=np.ones(before.shape[:2],dtype=bool);outside[776:916,77:217]=False
    assert np.array_equal(before[outside],after[outside])
    assert not np.array_equal(before[776:916,77:217],after[776:916,77:217])
    assert np.array_equal(before[776,77:217],after[776,77:217])
    isolate.assert_awaited_once()


@pytest.mark.asyncio
async def test_accepted_region_task_resumes_without_reference_inspection_or_resubmission(monkeypatch,tmp_path):
    monkeypatch.setattr(state,'STATE_DIR',tmp_path)
    isolate=AsyncMock(side_effect=lambda image,*args:image)
    monkeypatch.setattr(layout,'isolated_identity_view',isolate)
    async def first(sent,**kwargs):
        emit_progress(task_id='accepted-region',stage='running')
        raise SparkProviderError('lost connection',code='connection_failed')
    monkeypatch.setattr(creation,'generate_image',first)
    req=request()
    with pytest.raises(SparkProviderError):await creation.execute_node(req)
    async def resume(sent,**kwargs):
        assert kwargs=={'resume_task_id':'accepted-region'}
        assert sent.idempotency_key=='region-original'
        return SimpleNamespace(id='accepted-region',images=[SimpleNamespace(base64=base64.b64encode(layout.png_bytes(Image.new('RGB',(512,512),'white'))).decode(),mime_type='image/png')])
    monkeypatch.setattr(creation,'generate_image',resume)
    result=await creation.execute_node(req)
    assert Image.open(BytesIO(base64.b64decode(result['content']))).size==(576,1024)
    assert result['provider_task_id']=='accepted-region'
    isolate.assert_awaited_once()
    with pytest.raises(ValueError,match='上下文已变化'):
        await creation.execute_node(request(image_layout=[{**PLACEMENT,'center_x_percent':30}]))


def test_no_layout_preserves_legacy_task_fingerprint(monkeypatch,tmp_path):
    monkeypatch.setattr(state,'STATE_DIR',tmp_path)
    req=creation.CreationNodeRequest(kind='image',prompt='old task',idempotency_key='old')
    legacy=req.model_dump_json(exclude={'resume_task_id','image_operation','image_layout'})
    expected=hashlib.sha256((legacy+'\n'+runtime_config.get('aigc.spark.base_url')).encode()).hexdigest()
    assert state.CreationMediaState(req).record['fingerprint']==expected


@pytest.mark.asyncio
async def test_mismatched_scene_aspect_fails_without_paid_generation(monkeypatch):
    isolate=AsyncMock();monkeypatch.setattr(layout,'isolated_identity_view',isolate)
    req=request(input_images=[data(Image.new('RGB',(1024,576))),request().input_images[1]])
    with pytest.raises(ValueError,match='画幅一致'):await layout.prepare_region(req)
    isolate.assert_not_awaited()


def test_wrong_provider_patch_size_is_not_saved_as_final():
    region=(Image.new('RGB',(576,1024)),(77,776,217,916))
    with pytest.raises(ValueError,match='非512'):
        layout.compose_region(region,layout.png_bytes(Image.new('RGB',(1024,512))))


def test_planner_can_enable_clear_layout_without_changing_acceptance_and_locked_nodes():
    from tests.test_creation_draft_edit import editing_request, patch
    from agent.aigc import creation_planning as planning
    req=editing_request();req.automatic_mode=False;req.repair=None
    req.assets.append(planning.PlanningAsset(id='scene',name='空场景',mime_type='image/png'))
    original=req.current_plan['nodes'][1]
    original['aspect_ratio']='9:16'
    original['references'].append(dict(asset_id='scene',role='environment'))
    result=planning.parse_proposal(patch(image_layout=[PLACEMENT]),req)
    assert result.plan.nodes[1].content==original['content']
    assert result.plan.nodes[1].image_layout[0].subject_height_percent==10
    req.current_plan=result.plan.model_dump()
    assert planning.parse_proposal(patch(image_layout=[]),req).plan.nodes[1].image_layout==[]
    req.automatic_mode=True
    req.locked_node_ids.append('frame')
    with pytest.raises(ValueError):planning.parse_proposal(patch(image_layout=[]),req)


def test_layout_recipe_cannot_become_review_requirements():
    from agent.aigc.creation_review import ReviewRequest,review_context
    from tests.test_creation_draft_edit import editing_request
    from agent.aigc.creation_planning import CreativePlan
    req=editing_request();req.repair=None
    node=req.current_plan['nodes'][1];node['aspect_ratio']='9:16'
    node['references'].append(dict(asset_id='scene',role='environment'))
    node['image_layout']=[PLACEMENT]
    review=ReviewRequest(**req.model_dump(),node_id='frame',candidate_ids=['draft'])
    plan=CreativePlan.model_validate(req.current_plan)
    import json
    payload=json.loads(review_context(review,plan,plan.nodes[1])[0]['text'])
    assert 'image_layout' not in payload['review_target']
    assert payload['review_target']['content']==node['content']


def test_active_region_repair_is_not_forced_back_to_rejected_draft_edit():
    from tests.test_creation_draft_edit import editing_request
    from agent.aigc.creation_draft_edit import localized_repair_guidance,draft_edit_task
    req=editing_request();req.current_plan['nodes'][1]['image_layout']=[PLACEMENT]
    assert localized_repair_guidance(req)==''
    assert draft_edit_task(req) is None


def test_largest_supported_region_has_bounded_seam_free_composition():
    p=layout.ImagePlacement(**{**PLACEMENT,'center_x_percent':50,'center_y_percent':50,'subject_height_percent':25})
    box=layout.region_box(p,'9:16')
    original=Image.new('RGB',(576,1024),'#726652')
    result=layout.compose_region((original,box),layout.png_bytes(Image.new('RGB',(512,512),'white')))
    # A uniform generated offset must disappear at convergence, with no rectangle.
    assert np.array_equal(np.asarray(original),np.asarray(Image.open(BytesIO(result))))
