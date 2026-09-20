from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import base64
from io import BytesIO

import pytest
from pydantic import ValidationError
from PIL import Image

from agent.aigc import creation_pose_context as pose
from agent.aigc.creation_image_context import ImageReferenceContext
from agent.llm.base import LLMResponse
from tests.test_creation import PNG


def reference():
    return ImageReferenceContext(role='composition',note='Only foot contact, not the canyon or front view')


def guide():
    return pose.PoseGuide(facts=['Both feet rest on one shared support.','Standing balanced on a floating support.'])


@pytest.mark.asyncio
async def test_pose_cache_is_stable_private_and_rejects_changed_inputs(monkeypatch,tmp_path):
    monkeypatch.setattr(pose,'CONTEXT_DIR',tmp_path)
    extract=AsyncMock(return_value=guide());monkeypatch.setattr(pose,'extract_pose_guide',extract)
    first=await pose.pose_only_guide(PNG,reference(),'Rear view in a golden forest','key')
    assert await pose.pose_only_guide(PNG,reference(),'Rear view in a golden forest','key')==first
    assert extract.await_count==1
    stored=next(tmp_path.glob('*.json')).read_text()
    assert PNG not in stored and 'golden forest' not in stored and 'canyon' not in stored
    for data,ref,target in [(PNG,reference(),'Front view'),(PNG+'different',reference(),'Rear view in a golden forest'),
        (PNG,ImageReferenceContext(role='composition',note='Copy front view'),'Rear view in a golden forest')]:
        with pytest.raises(ValueError,match='上下文已变化'):
            await pose.pose_only_guide(data,ref,target,'key')
    assert extract.await_count==1


@pytest.mark.asyncio
async def test_empty_guide_is_frozen_and_failure_never_creates_a_cache(monkeypatch,tmp_path):
    monkeypatch.setattr(pose,'CONTEXT_DIR',tmp_path)
    extract=AsyncMock(return_value=pose.PoseGuide());monkeypatch.setattr(pose,'extract_pose_guide',extract)
    assert await pose.pose_only_guide(PNG,reference(),'rear','empty')==''
    assert await pose.pose_only_guide(PNG,reference(),'rear','empty')==''
    assert extract.await_count==1
    extract.side_effect=RuntimeError('unavailable')
    with pytest.raises(RuntimeError):await pose.pose_only_guide(PNG,reference(),'rear','failed')
    assert len(list(tmp_path.glob('*.json')))==1 and not list(tmp_path.glob('*.pending'))


@pytest.mark.parametrize('value',[
    {'facts':['Blue canyon behind a front-facing rabbit.']},
    {'facts':[], 'background':'canyon'},
    {'facts':['Standing upright.']*13},
])
def test_pose_vocabulary_cannot_transmit_source_scenery_or_identity(value):
    with pytest.raises(ValidationError):pose.PoseGuide.model_validate(value)


@pytest.mark.asyncio
async def test_extraction_has_scoped_inputs_and_repairs_invalid_free_text(monkeypatch):
    provider=SimpleNamespace(client=SimpleNamespace(close=AsyncMock()),chat=AsyncMock(side_effect=[
        LLMResponse(content=json.dumps({'facts':['blue canyon']})),
        LLMResponse(content=guide().model_dump_json())]))
    monkeypatch.setattr(pose,'create_provider',lambda:provider)
    data=BytesIO();Image.new('RGB',(8,8),'red').save(data,format='PNG')
    image='data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()
    result=await pose.extract_pose_guide(image,reference(),'Rear view in a golden forest')
    assert result==guide() and provider.chat.await_count==2
    messages=provider.chat.call_args.args[0]
    payload=json.loads(messages[1].content[0]['text'])
    assert payload=={'reference_note':reference().note,'target_brief':'Rear view in a golden forest'}
    assert len([p for p in messages[1].content if p['type']=='image_url'])==1
    assert '不能附带正面朝向' in messages[0].content
    provider.client.close.assert_awaited_once()
