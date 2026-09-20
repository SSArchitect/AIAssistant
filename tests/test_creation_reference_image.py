import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from agent.aigc import creation,creation_media_state
from tests.test_creation import PNG,request

SECOND='data:image/png;base64,'+base64.b64encode(b'scene').decode()
THIRD='data:image/png;base64,'+base64.b64encode(b'style').decode()

@pytest.fixture(autouse=True)
def isolate(monkeypatch,tmp_path):
    monkeypatch.setattr(creation_media_state,'STATE_DIR',tmp_path)

@pytest.mark.asyncio
async def test_shot_uses_ordered_identity_and_environment_with_single_scene_rules(monkeypatch):
    generate=AsyncMock(return_value=SimpleNamespace(id='shot',images=[SimpleNamespace(base64=PNG.split(',')[1],mime_type='image/png')]))
    monkeypatch.setattr(creation,'generate_image',generate)
    await creation.execute_node(request(image_purpose='shot_reference',input_images=[PNG,SECOND],image_references=[dict(role='identity',note='兔大侠'),dict(role='environment',note='荧光菇谷')]))
    sent=generate.call_args.args[0]
    assert sent.mode=='reference_to_image' and sent.reference_image_data_urls==[PNG,SECOND]
    assert sent.character_style is None and sent.image_data_url is None
    assert 'Picture 1' in sent.prompt and 'Picture 2' in sent.prompt and '荧光菇谷' in sent.prompt
    assert 'single' in sent.prompt.lower() and 'layout' in sent.prompt.lower()


@pytest.mark.asyncio
async def test_scene_reuses_two_environment_pixels_without_character_identity(monkeypatch):
    generate = AsyncMock(return_value=SimpleNamespace(id='scene', images=[SimpleNamespace(base64=PNG.split(',')[1], mime_type='image/png')]))
    monkeypatch.setattr(creation, 'generate_image', generate)
    await creation.execute_node(request(image_purpose='scene', input_images=[PNG, SECOND],
        image_references=[dict(role='environment', note='远景森林'), dict(role='composition', note='上方菌盖')]))
    sent = generate.call_args.args[0]
    assert sent.mode == 'reference_to_image' and sent.reference_image_data_urls == [PNG, SECOND]
    assert 'Picture 1' in sent.prompt and 'Picture 2' in sent.prompt
    assert 'Unpopulated environment' in sent.prompt

@pytest.mark.asyncio
async def test_style_guide_is_abstracted_not_uploaded_and_numbering_is_compacted(monkeypatch):
    from agent.aigc import creation_reference_images as refs
    style=AsyncMock(side_effect=lambda prompt,*args:prompt+'\nRendering style: ink illustration.')
    monkeypatch.setattr(refs,'style_only_prompt',style)
    generate=AsyncMock(return_value=SimpleNamespace(id='shot',images=[SimpleNamespace(base64=PNG.split(',')[1],mime_type='image/png')]))
    monkeypatch.setattr(creation,'generate_image',generate)
    req=request(image_purpose='shot_reference',input_images=[THIRD,PNG,SECOND],image_references=[dict(role='style'),dict(role='identity'),dict(role='environment')])
    await creation.execute_node(req)
    sent=generate.call_args.args[0]
    assert sent.reference_image_data_urls==[PNG,SECOND] and 'Picture 3' not in sent.prompt
    assert 'ink illustration' in sent.prompt and style.await_count==1
    await creation.execute_node(req.model_copy(update={'resume_task_id':'shot'}))
    assert style.await_count==1 and generate.call_args.kwargs=={'resume_task_id':'shot'}


@pytest.mark.asyncio
async def test_cross_scene_pose_reference_cannot_upload_its_background_or_identity(monkeypatch):
    from agent.aigc import creation_reference_images as refs
    pose=AsyncMock(return_value='Both feet rest on one shared support.')
    monkeypatch.setattr(refs,'pose_only_guide',pose,raising=False)
    generate=AsyncMock(return_value=SimpleNamespace(id='shot',images=[SimpleNamespace(base64=PNG.split(',')[1],mime_type='image/png')]))
    monkeypatch.setattr(creation,'generate_image',generate)
    req=request(image_purpose='shot_reference',input_images=[SECOND,THIRD,PNG],
        image_references=[dict(role='environment',note='golden forest'),dict(role='composition',note='Only foot contact, not the blue canyon'),dict(role='identity',note='rabbit')])
    req.prompt='Use Picture 1 environment, Picture 2 contact, Picture 3 identity. Rear view.'
    await creation.execute_node(req)
    sent=generate.call_args.args[0]
    assert sent.reference_image_data_urls==[SECOND,PNG] and THIRD not in sent.reference_image_data_urls
    assert 'Picture 3' not in sent.prompt and 'Picture 2 identity' in sent.prompt
    assert 'Both feet rest on one shared support.' in sent.prompt and 'blue canyon' not in sent.prompt
    assert 'Rear view.' in sent.prompt
    assert pose.call_args.args[:3]==(THIRD,req.image_references[1],req.prompt)
    await creation.execute_node(req.model_copy(update={'resume_task_id':'shot'}))
    assert pose.await_count==1 and generate.call_args.kwargs=={'resume_task_id':'shot'}


@pytest.mark.asyncio
async def test_failed_pose_isolation_does_not_fall_back_to_source_pixels(monkeypatch):
    from agent.aigc import creation_reference_images as refs
    monkeypatch.setattr(refs,'pose_only_guide',AsyncMock(side_effect=ValueError('pose unavailable')))
    generate=AsyncMock();monkeypatch.setattr(creation,'generate_image',generate)
    with pytest.raises(ValueError,match='pose unavailable'):
        await creation.execute_node(request(image_purpose='shot_reference',input_images=[PNG,SECOND],
            image_references=[dict(role='environment'),dict(role='composition')]))
    assert not generate.called


@pytest.mark.asyncio
async def test_standalone_composition_reference_remains_a_native_image_input(monkeypatch):
    from agent.aigc import creation_reference_images as refs
    pose=AsyncMock();monkeypatch.setattr(refs,'pose_only_guide',pose)
    generate=AsyncMock(return_value=SimpleNamespace(id='shot',images=[SimpleNamespace(base64=PNG.split(',')[1],mime_type='image/png')]))
    monkeypatch.setattr(creation,'generate_image',generate)
    await creation.execute_node(request(image_purpose='shot_reference',input_images=[PNG],image_references=[dict(role='composition')]))
    assert generate.call_args.args[0].reference_image_data_urls==[PNG] and not pose.called

@pytest.mark.parametrize('options',[
    dict(input_images=[PNG,SECOND,THIRD,PNG]),
    dict(input_images=[PNG,SECOND],character_style='chibi'),
    dict(input_images=[PNG,PNG]),
    dict(input_images=[PNG,SECOND],image_references=[dict(role='identity')])])
def test_bad_combinations_rejected_before_provider(options):
    with pytest.raises(ValidationError):request(**options)


@pytest.mark.asyncio
async def test_reference_overhead_is_budgeted_before_image_submission(monkeypatch):
    from agent.aigc import creation_reference_images as refs
    compact=AsyncMock(return_value='白兔背侧仰望，双脚站在胡萝卜剑上。')
    monkeypatch.setattr(refs,'fit_image_prompt',compact,raising=False)
    generate=AsyncMock(return_value=SimpleNamespace(id='shot',images=[SimpleNamespace(base64=PNG.split(',')[1],mime_type='image/png')]))
    monkeypatch.setattr(creation,'generate_image',generate)
    req=request(image_purpose='shot_reference',input_images=[PNG,SECOND],
        image_references=[dict(role='environment',note='环境职责。'*70),dict(role='identity',note='身份职责。'*70)])
    req.prompt='远景场景。'*700
    await creation.execute_node(req)
    sent=generate.call_args.args[0]
    assert len(sent.prompt)<=4000 and compact.await_count==1
    assert '环境职责。'*70 in sent.prompt and '身份职责。'*70 in sent.prompt
    assert sent.reference_image_data_urls==[PNG,SECOND]
    assert compact.call_args.args[1]<len(req.prompt)
    assert req.prompt=='远景场景。'*700


@pytest.mark.asyncio
async def test_accepted_task_resume_skips_prompt_compilation_and_never_reextracts(monkeypatch):
    from agent.aigc import creation_reference_images as refs
    compact=AsyncMock(side_effect=AssertionError('resume must not rewrite the accepted task'))
    pose=AsyncMock(side_effect=AssertionError('resume must not extract again'))
    monkeypatch.setattr(refs,'fit_image_prompt',compact,raising=False)
    monkeypatch.setattr(refs,'pose_only_guide',pose)
    generate=AsyncMock(return_value=SimpleNamespace(id='accepted',images=[SimpleNamespace(base64=PNG.split(',')[1],mime_type='image/png')]))
    monkeypatch.setattr(creation,'generate_image',generate)
    req=request(resume_task_id='accepted',image_purpose='shot_reference',input_images=[PNG,SECOND,THIRD],
        image_references=[dict(role='environment',note='env'*100),dict(role='composition'),dict(role='identity',note='identity'*40)])
    req.prompt='x'*3900
    await creation.execute_node(req)
    assert generate.call_args.kwargs=={'resume_task_id':'accepted'}
    assert not compact.called and not pose.called
