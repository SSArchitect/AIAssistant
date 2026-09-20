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

@pytest.mark.parametrize('options',[
    dict(input_images=[PNG,SECOND,THIRD,PNG]),
    dict(input_images=[PNG,SECOND],character_style='chibi'),
    dict(input_images=[PNG,PNG]),
    dict(input_images=[PNG,SECOND],image_references=[dict(role='identity')])])
def test_bad_combinations_rejected_before_provider(options):
    with pytest.raises(ValidationError):request(**options)
