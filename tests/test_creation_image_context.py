"""Reference-role regressions: style guides must never become source characters."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from agent.aigc import creation, creation_image_context as context
from agent.aigc.spark_client import SparkImageClient
from agent.llm.base import LLMResponse
from tests.test_creation import PNG, request


@pytest.fixture(autouse=True)
def isolated_media_state(monkeypatch, tmp_path):
    from agent.aigc import creation_media_state
    monkeypatch.setattr(creation_media_state, "STATE_DIR", tmp_path / "media-state")


def profile():
    return context.VisualStyle(medium='flat cartoon illustration', linework='bold clean outlines', shading='flat cel shading',
        palette='warm saturated colors', shapes='rounded stylized shapes', texture='smooth clean surfaces')


@pytest.mark.asyncio
@pytest.mark.parametrize('purpose', ['key_visual', 'scene'])
async def test_atmosphere_recomposes_instead_of_editing_character_sheet(monkeypatch, tmp_path, purpose):
    monkeypatch.setattr(context, 'CONTEXT_DIR', tmp_path)
    traits = context.CompositionTraits(subject_role='scale_figure', subject='white rabbit swordsman', appearance='long ears',
        materials_or_clothing='brown clothes and red cape', distinctive_details='carrot sword')
    extract = AsyncMock(return_value=traits)
    monkeypatch.setattr(context, 'extract_composition_traits', extract)
    generate = AsyncMock(return_value=SimpleNamespace(id='p', images=[SimpleNamespace(base64=PNG.split(',')[1], mime_type='image/png')]))
    monkeypatch.setattr(creation, 'generate_image', generate)
    req = request(image_purpose=purpose, input_images=[PNG], image_references=[dict(role='identity', note='tiny silhouette only')])
    req.prompt = 'Vast mushroom kingdom panorama. A tiny rabbit silhouette in the lower foreground.'
    await creation.execute_node(req)
    sent = generate.call_args.args[0]
    assert SparkImageClient.payload(sent)['template'] == 'image.text.v1'
    assert sent.image_data_url is None and sent.character_style is None
    assert req.prompt in sent.prompt and 'at most 5%' in sent.prompt
    assert 'carrot sword' not in sent.prompt and 'brown clothes' not in sent.prompt
    assert extract.call_args.args == (PNG, 'tiny silhouette only', req.prompt)
    await creation.execute_node(req)
    assert extract.await_count == 1 and generate.call_args_list[0].args[0] == generate.call_args_list[1].args[0]
    assert PNG not in next(tmp_path.glob('*.json')).read_text()


@pytest.mark.asyncio
async def test_composition_analysis_failure_does_not_edit_source(monkeypatch, tmp_path):
    monkeypatch.setattr(context, 'CONTEXT_DIR', tmp_path)
    monkeypatch.setattr(context, 'extract_composition_traits', AsyncMock(side_effect=RuntimeError('failed')))
    generate = AsyncMock(); monkeypatch.setattr(creation, 'generate_image', generate)
    with pytest.raises(RuntimeError):
        await creation.execute_node(request(image_purpose='key_visual', input_images=[PNG], image_references=[dict(role='identity')]))
    assert generate.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('character_style', ['', 'chibi'])
async def test_style_reference_is_abstracted_and_never_uploaded_as_source_pixels(monkeypatch,tmp_path,character_style):
    monkeypatch.setattr(context,'CONTEXT_DIR',tmp_path)
    extract=AsyncMock(return_value=profile());monkeypatch.setattr(context,'extract_visual_style',extract)
    generate=AsyncMock(return_value=SimpleNamespace(id='provider',images=[SimpleNamespace(base64=PNG.split(',')[1],mime_type='image/png')]))
    monkeypatch.setattr(creation,'generate_image',generate)
    req=request(input_images=[PNG],image_references=[dict(role='style',note='只参考线条和上色，不用兔子或森林构图')],character_style=character_style)
    req.prompt='Single human girl Xiaosan wearing a mushroom cap, front view, plain background.'
    await creation.execute_node(req)
    sent=generate.call_args.args[0];wire=SparkImageClient.payload(sent)
    assert sent.mode=='text_to_image' and sent.image_data_url is None and sent.character_style is None
    assert wire['template']=='image.text.v1' and 'image_asset_id' not in wire['input'] and 'mode' not in wire
    assert sent.prompt.startswith(req.prompt) and 'flat cartoon illustration' in sent.prompt
    assert extract.call_args.args[1]==req.image_references[0].note
    # Identical retries use exactly the same frozen preparation even across cache reload.
    await creation.execute_node(req)
    assert extract.await_count==1 and generate.call_args_list[0].args[0]==generate.call_args_list[1].args[0]
    record=next(tmp_path.glob('*.json')).read_text()
    assert PNG not in record and 'human girl' not in record
    req.prompt='Different character'
    with pytest.raises(ValueError,match='上下文已变化'):await creation.execute_node(req)
    assert generate.await_count==2


@pytest.mark.asyncio
async def test_identity_edit_preserves_source_and_does_not_invoke_style_extraction(monkeypatch):
    extract=AsyncMock();monkeypatch.setattr(context,'extract_visual_style',extract)
    generate=AsyncMock(return_value=SimpleNamespace(id='p',images=[SimpleNamespace(base64=PNG.split(',')[1],mime_type='image/png')]))
    monkeypatch.setattr(creation,'generate_image',generate)
    await creation.execute_node(request(input_images=[PNG],image_references=[dict(role='identity',note='保留原角色身份')],character_style='anime'))
    sent=generate.call_args.args[0]
    assert sent.mode=='character_stylization' and sent.image_data_url==PNG and '保留原角色身份' in sent.prompt
    assert extract.await_count==0


@pytest.mark.asyncio
async def test_failed_style_analysis_never_falls_back_to_editing_source_image(monkeypatch,tmp_path):
    monkeypatch.setattr(context,'CONTEXT_DIR',tmp_path)
    monkeypatch.setattr(context,'extract_visual_style',AsyncMock(side_effect=RuntimeError('analysis failed')))
    generate=AsyncMock();monkeypatch.setattr(creation,'generate_image',generate)
    with pytest.raises(RuntimeError):await creation.execute_node(request(input_images=[PNG],image_references=[dict(role='style')]))
    assert generate.await_count==0 and list(tmp_path.glob('*.json'))==[]


def test_style_vocabulary_excludes_identity_and_never_truncates_target_brief():
    value=profile().model_dump();value['shapes']='rabbit ears and cloak'
    with pytest.raises(ValidationError):context.VisualStyle(**value)
    value=profile().model_dump();value['subject']='rabbit'
    with pytest.raises(ValidationError):context.VisualStyle(**value)
    prompt='人类小女孩' * 799
    result=context.render_style_prompt(prompt,profile())
    assert result.startswith(prompt) and len(result)<=4000
    assert context.render_style_prompt('x'*4000,profile())=='x'*4000
    for bad in [dict(input_images=[PNG],image_references=[dict(role='first_frame')]),dict(image_references=[dict(role='style')])]:
        with pytest.raises(ValidationError):request(**bad)


@pytest.mark.asyncio
async def test_visual_analysis_gets_only_reference_and_closed_style_contract(monkeypatch):
    from agent.aigc import creation_planning
    monkeypatch.setattr(creation_planning,'image_preview',lambda value:value)
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=profile().model_dump_json())))
    monkeypatch.setattr(context,'create_provider',lambda:provider)
    assert await context.extract_visual_style(PNG,'参考上色')==profile()
    system,user=provider.chat.call_args.args[0]
    assert '禁止提取角色身份' in system.content and provider.chat.call_args.kwargs['tools'] is None
    payload=json.loads(user.content[0]['text'])
    assert payload=={'reference_role':'style','reference_note':'参考上色'}
    assert user.content[1]['image_url']['url']==PNG


def test_composition_role_limits_reference_detail_and_preserves_target():
    facts = dict(subject='white rabbit', appearance='long ears', materials_or_clothing='old red cape', distinctive_details='ordinary sword')
    target = 'A vast valley, tiny rabbit with a carrot sword.'
    small = context.render_composition_prompt(target, context.CompositionTraits(subject_role='scale_figure', **facts))
    assert target in small and 'at most 5%' in small
    assert 'ordinary sword' not in small and 'old red cape' not in small
    empty = context.render_composition_prompt('Empty valley', context.CompositionTraits(subject_role='absent', **facts))
    assert 'white rabbit' not in empty and 'unpopulated' in empty
    featured = context.render_composition_prompt('Portrait in a valley', context.CompositionTraits(subject_role='featured', **facts))
    assert 'long ears' in featured and 'old red cape' in featured
    assert context.render_composition_prompt('x'*4000, context.CompositionTraits(subject_role='featured', **facts)) == 'x'*4000


@pytest.mark.asyncio
async def test_composition_extractor_uses_target_scale_and_explicit_changes(monkeypatch):
    from agent.aigc import creation_planning
    monkeypatch.setattr(creation_planning, 'image_preview', lambda value:value)
    traits = context.CompositionTraits(subject_role='scale_figure', subject='white rabbit', appearance='', materials_or_clothing='', distinctive_details='')
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=traits.model_dump_json())))
    monkeypatch.setattr(context, 'create_provider', lambda:provider)
    target = 'Huge canyon, distant tiny silhouette. Replace the ordinary sword with a carrot sword.'
    assert await context.extract_composition_traits(PNG, 'Character identity', target) == traits
    system, user = provider.chat.call_args.args[0]
    assert '禁止按参考图中的大小判断' in system.content and '冲突的道具' in system.content
    assert json.loads(user.content[0]['text']) == dict(target_brief=target, reference_note='Character identity')
    assert user.content[1]['image_url']['url'] == PNG
