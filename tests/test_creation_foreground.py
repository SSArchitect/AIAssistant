import base64
import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from PIL import Image, ImageDraw

from agent.aigc import creation, creation_image_layout as layout, creation_media_state as state
from agent.aigc.progress import emit_progress
from agent.aigc.spark_client import SparkProviderError
from tests.test_creation_image_layout import request, PLACEMENT, data


def keyed(color=(255, 0, 255), clipped=False):
    im = Image.new('RGB', (512, 512), color)
    draw = ImageDraw.Draw(im)
    draw.ellipse((170, 0 if clipped else 70, 300, 330), fill=(245, 245, 245))
    draw.rectangle((215, 300, 270, 395), fill=(110, 65, 30))
    draw.rectangle((110, 385, 385, 409), fill=(235, 100, 25))
    return im


def foreground_request(**changes):
    return request(image_layout=[{**PLACEMENT, 'composite_mode': 'foreground_v1'}], **changes)


def test_opt_in_mode_preserves_old_layout_and_task_fingerprint(monkeypatch, tmp_path):
    monkeypatch.setattr(state, 'STATE_DIR', tmp_path)
    req = request()
    serialized = req.model_dump_json(exclude={'resume_task_id', 'image_operation'})
    assert 'composite_mode' not in serialized
    expected = hashlib.sha256((serialized+'\n'+state.runtime_config.get('aigc.spark.base_url')).encode()).hexdigest()
    assert state.CreationMediaState(req).record['fingerprint'] == expected
    assert foreground_request().image_layout[0].composite_mode == 'foreground_v1'
    with pytest.raises(ValueError): layout.ImagePlacement(**PLACEMENT, composite_mode='unknown')


def test_key_choice_avoids_existing_character_color():
    from agent.aigc.creation_foreground import choose_key
    assert choose_key(Image.new('RGB', (32,32),'white'), '') == 'magenta'
    assert choose_key(Image.new('RGB', (32,32),'magenta'), '') != 'magenta'
    assert choose_key(Image.new('RGB', (32,32),'white'), 'magenta cape') != 'magenta'


def test_alpha_composition_keeps_white_features_and_original_scene_pixels():
    from agent.aigc.creation_foreground import ForegroundRegion, composite_foreground
    before = Image.new('RGB', (576,1024), (17,29,41))
    placement = layout.ImagePlacement(center_x_percent=32,center_y_percent=18,subject_height_percent=4,subject_prompt='rider',composite_mode='foreground_v1')
    result = Image.open(BytesIO(composite_foreground(ForegroundRegion(before,placement,'magenta'),layout.png_bytes(keyed()))))
    raw=np.asarray(result); original=np.asarray(before); changed=np.any(raw!=original,axis=2)
    ys,xs=np.where(changed)
    assert 37 <= ys.max()-ys.min()+1 <= 42
    assert abs((xs.min()+xs.max())/2-576*.32)<2 and abs((ys.min()+ys.max())/2-1024*.18)<2
    assert np.any(np.all(raw==(245,245,245),axis=2))
    assert np.array_equal(raw[~changed],original[~changed])
    assert not np.any((raw[:,:,0]>180)&(raw[:,:,2]>180)&(raw[:,:,1]<60))


@pytest.mark.parametrize('failure',['clipped','no_key','no_subject','wrong_size','off_canvas'])
def test_invalid_foreground_never_becomes_a_completed_composite(failure):
    from agent.aigc.creation_foreground import ForegroundRegion,composite_foreground
    im=keyed(clipped=failure=='clipped')
    if failure=='no_key': im=Image.new('RGB',(512,512),'white')
    if failure=='no_subject':im=Image.new('RGB',(512,512),'magenta')
    if failure=='wrong_size':im=im.resize((256,256))
    p=layout.ImagePlacement(center_x_percent=0 if failure=='off_canvas' else 32,center_y_percent=18,subject_height_percent=4,subject_prompt='rider')
    with pytest.raises(SparkProviderError) as e:composite_foreground(ForegroundRegion(Image.new('RGB',(576,1024)),p,'magenta'),layout.png_bytes(im))
    assert e.value.code=='invalid_output'


@pytest.mark.asyncio
async def test_two_stage_recovery_keeps_child_and_final_task_ids_separate(monkeypatch,tmp_path):
    from agent.aigc import creation_foreground as fg
    monkeypatch.setattr(state,'STATE_DIR',tmp_path)
    monkeypatch.setattr(layout,'isolated_identity_view',AsyncMock(side_effect=lambda image,*args:image))
    # Foreground helper uses the same identity extractor but owns its child's checkpoint.
    monkeypatch.setattr(fg,'isolated_identity_view',AsyncMock(side_effect=lambda image,*args:image))
    child_calls=[]
    async def child(req,**kw):
        child_calls.append((req,kw))
        if len(child_calls)==1:
            emit_progress(task_id='child-real',stage='running')
            raise SparkProviderError('disconnected',code='connection_failed',task_id='child-real')
        assert kw=={'resume_task_id':'child-real'}
        return SimpleNamespace(id='child-real',images=[SimpleNamespace(base64=base64.b64encode(layout.png_bytes(keyed())).decode(),mime_type='image/png')])
    monkeypatch.setattr(fg,'foreground_client',lambda:SimpleNamespace(generate=child))
    final_calls=[]
    async def final(req,**kw):
        final_calls.append((req,kw))
        if len(final_calls)==1:
            assert len(req.reference_image_data_urls)==1
            prepared=layout.read_image(req.reference_image_data_urls[0]);assert prepared.size==(512,512)
            assert prepared.getpixel((10,10))==(255,0,255)
            emit_progress(task_id='final-real',stage='running')
            raise SparkProviderError('disconnected',code='connection_failed',task_id='final-real')
        assert kw=={'resume_task_id':'final-real'}
        return SimpleNamespace(id='final-real',images=[SimpleNamespace(base64=base64.b64encode(layout.png_bytes(keyed())).decode(),mime_type='image/png')])
    monkeypatch.setattr(creation,'generate_image',final)
    req=foreground_request()
    with pytest.raises(SparkProviderError) as first:await creation.execute_node(req)
    assert first.value.task_id is None  # Gateway must not adopt the intermediate task as final.
    assert state.CreationMediaState(req).task_id is None
    with pytest.raises(SparkProviderError):await creation.execute_node(req)
    assert state.CreationMediaState(req).task_id=='final-real'
    result=await creation.execute_node(req)
    assert result['provider_task_id']=='final-real'
    assert len(child_calls)==2 and len(final_calls)==2
    assert child_calls[0][0].idempotency_key!=req.idempotency_key
    assert any(tmp_path.glob('*.foreground.png'))
    assert Image.open(BytesIO(base64.b64decode(result['content']))).size==(576,1024)


def test_key_selection_fails_closed_when_all_key_colors_are_in_identity():
    from agent.aigc.creation_foreground import choose_key
    im=Image.new('RGB',(128,128));draw=ImageDraw.Draw(im)
    for index,color in enumerate(['magenta','green','cyan','blue']):draw.rectangle((index*32,0,index*32+31,127),fill=color)
    with pytest.raises(SparkProviderError):choose_key(im,'')


def test_detached_large_prop_is_not_silently_dropped():
    from agent.aigc.creation_foreground import foreground_layer
    im=keyed();ImageDraw.Draw(im).rectangle((380,50,460,150),fill='white')
    with pytest.raises(SparkProviderError):foreground_layer(layout.png_bytes(im),'magenta')


@pytest.mark.asyncio
async def test_completed_child_is_cached_until_final_submission_succeeds(monkeypatch,tmp_path):
    from agent.aigc import creation_foreground as fg
    monkeypatch.setattr(state,'STATE_DIR',tmp_path)
    monkeypatch.setattr(fg,'isolated_identity_view',AsyncMock(side_effect=lambda image,*args:image))
    calls=[]
    async def child(req,**kw):
        calls.append(kw);emit_progress(task_id='child-cached',stage='completed')
        return SimpleNamespace(id='child-cached',images=[SimpleNamespace(base64=base64.b64encode(layout.png_bytes(keyed())).decode(),mime_type='image/png')])
    monkeypatch.setattr(fg,'foreground_client',lambda:SimpleNamespace(generate=child))
    req=foreground_request()
    first=await layout.prepare_region(req)
    second=await layout.prepare_region(req)
    assert len(calls)==1 and first[1]==second[1]
    saved=next(tmp_path.glob('*.foreground.png'));assert saved.stat().st_mode & 0o777==0o600
    saved.write_bytes(b'incomplete cache')
    await layout.prepare_region(req)
    assert calls[-1]=={'resume_task_id':'child-cached'} and len(calls)==2


@pytest.mark.asyncio
async def test_maximum_subject_and_reference_notes_fit_both_generation_requests(monkeypatch,tmp_path):
    from agent.aigc import creation_foreground as fg
    monkeypatch.setattr(state,'STATE_DIR',tmp_path)
    monkeypatch.setattr(fg,'isolated_identity_view',AsyncMock(side_effect=lambda image,*args:image))
    async def child(req,**kw):
        assert len(req.prompt)<=4000
        return SimpleNamespace(id='child',images=[SimpleNamespace(base64=base64.b64encode(layout.png_bytes(keyed())).decode(),mime_type='image/png')])
    monkeypatch.setattr(fg,'foreground_client',lambda:SimpleNamespace(generate=child))
    req=request(image_layout=[{**PLACEMENT,'composite_mode':'foreground_v1','subject_prompt':'兔'*1800}],image_references=[dict(role='environment'),dict(role='identity',note='姿'*500)],idempotency_key='x'*128)
    _,prepared=await layout.prepare_region(req);assert len(prepared['prompt'])<=4000


@pytest.mark.asyncio
async def test_foreground_v2_isolates_environment_and_uses_one_recoverable_job(monkeypatch,tmp_path):
    from agent.aigc import creation_foreground as fg
    monkeypatch.setattr(state,'STATE_DIR',tmp_path)
    inspector=AsyncMock(side_effect=lambda image,*args:image)
    monkeypatch.setattr(fg,'isolated_identity_view',inspector)
    monkeypatch.setattr(fg,'foreground_client',lambda:pytest.fail('v2 must not launch an intermediate job'))
    calls=[]
    async def final(req,**kw):
        calls.append(req)
        assert len(req.reference_image_data_urls)==1
        if len(calls)==1:
            canvas=layout.read_image(req.reference_image_data_urls[0])
            assert canvas.size==(512,512) and canvas.getpixel((0,0))==(255,0,255)
            assert canvas.getpixel((256,256))==(255,255,255)
            assert not np.any(np.all(np.asarray(canvas)==(114,102,82),axis=2))
            assert 'SCENE_NOTE_DO_NOT_CONDITION' not in req.prompt
            assert 'warm golden light' in req.prompt
            emit_progress(task_id='single-real',stage='running')
            raise SparkProviderError('disconnected',code='connection_failed',task_id='single-real')
        assert kw=={'resume_task_id':'single-real'}
        return SimpleNamespace(id='single-real',images=[SimpleNamespace(base64=base64.b64encode(layout.png_bytes(keyed())).decode(),mime_type='image/png')])
    monkeypatch.setattr(creation,'generate_image',final)
    req=request(image_layout=[{**PLACEMENT,'composite_mode':'foreground_v2','subject_prompt':'rear rider with warm golden light'}],image_references=[dict(role='environment'),dict(role='identity',note='SCENE_NOTE_DO_NOT_CONDITION')])
    with pytest.raises(SparkProviderError):await creation.execute_node(req)
    assert state.CreationMediaState(req).task_id=='single-real'
    result=await creation.execute_node(req)
    assert result['provider_task_id']=='single-real'
    assert len(calls)==2 and inspector.await_count==1
    assert not list(tmp_path.glob('*.foreground.png'))
    assert Image.open(BytesIO(base64.b64decode(result['content']))).size==(576,1024)
