import base64
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
import pytest
from pydantic import ValidationError

from agent.aigc import creation_identity_context as identity
from agent.aigc.creation_image_context import ImageReferenceContext
from agent.llm.base import LLMResponse


def sheet():
    return identity.IdentitySheet(layout='multiple_views_of_one_subject',views=[
        dict(left=0,top=0,right=500,bottom=1000,orientation='front'),
        dict(left=500,top=0,right=1000,bottom=1000,orientation='side')],selected_index=1)


def pixels():
    image=Image.new('RGB',(100,80),'red');image.paste('blue',(50,0,100,80))
    output=BytesIO();image.save(output,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode()


def test_selected_view_contains_only_original_pixels_without_neighbour_or_resizing():
    result=identity.crop_identity_view(pixels(),sheet())
    cropped=Image.open(BytesIO(base64.b64decode(result.split(',')[1])))
    assert cropped.size==(50,80) and set(cropped.getdata())=={(0,0,255)}


@pytest.mark.parametrize('layout',['single_view','multiple_subjects','unknown'])
def test_single_view_distinct_people_or_uncertainty_never_removes_an_identity(layout):
    original=pixels()
    assert identity.crop_identity_view(original,identity.IdentitySheet(layout=layout,views=[],selected_index=-1))==original


def test_invalid_or_overlapping_sheet_regions_cannot_crop_multiple_views():
    for change in [dict(selected_index=-1),dict(selected_index=2),dict(layout='single_view')]:
        with pytest.raises(ValidationError):identity.IdentitySheet.model_validate({**sheet().model_dump(),**change})
    value=sheet().model_dump();value['views'][0]['right']=700
    with pytest.raises(ValidationError):identity.IdentitySheet.model_validate(value)
    value['views'][0]['right']=0
    with pytest.raises(ValidationError):identity.IdentitySheet.model_validate(value)


@pytest.mark.asyncio
async def test_sheet_choice_is_cached_but_same_key_cannot_silently_change_context(monkeypatch,tmp_path):
    monkeypatch.setattr(identity,'CONTEXT_DIR',tmp_path)
    inspect=AsyncMock(return_value=sheet());monkeypatch.setattr(identity,'inspect_identity_sheet',inspect)
    args=(pixels(),ImageReferenceContext(role='identity',note='衣服身份'),'背侧仰望','key')
    first=await identity.isolated_identity_view(*args)
    assert await identity.isolated_identity_view(*args)==first and inspect.await_count==1
    saved=next(tmp_path.glob('*.json')).read_text()
    assert 'data:image' not in saved and '背侧仰望' not in saved
    with pytest.raises(identity.ReferenceViewError):await identity.isolated_identity_view(args[0],args[1],'different','key')


@pytest.mark.asyncio
async def test_model_output_is_validated_and_provider_closed(monkeypatch):
    good=sheet().model_dump(exclude={'selected_index'});bad=json.loads(json.dumps(good));bad['views'][0]['right']=700
    provider=SimpleNamespace(max_tokens=None,client=SimpleNamespace(close=AsyncMock()),chat=AsyncMock(side_effect=[
        LLMResponse(content=json.dumps(bad)),LLMResponse(content=json.dumps(good))]))
    monkeypatch.setattr(identity,'create_provider',lambda:provider)
    result=await identity.inspect_identity_sheet(pixels(),ImageReferenceContext(role='identity',note='identity only'),'rear view')
    assert result.selected_index==1 and provider.chat.await_count==2 and provider.client.close.await_count==1
    parts=provider.chat.call_args.args[0][1].content
    assert len(parts)==1 and parts[0]['type']=='image_url'
    assert 'rear view' not in str(provider.chat.call_args.args[0]) and 'identity only' not in str(provider.chat.call_args.args[0])


def test_missing_rear_view_uses_real_side_instead_of_top_or_invented_back():
    views=sheet().views+[identity.IdentityView(left=0,top=0,right=1000,bottom=1000,orientation='overhead')]
    assert identity.select_identity_view(views,'rear three-quarter view')==1
    assert identity.select_identity_view(views,'俯视')==2


@pytest.mark.asyncio
async def test_single_person_detection_may_include_unused_view_details_without_retry(monkeypatch):
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(
        layout='single_view',views=[sheet().views[0].model_dump()])))))
    monkeypatch.setattr(identity,'create_provider',lambda:provider)
    result=await identity.inspect_identity_sheet(pixels(),ImageReferenceContext(role='identity'),'rear view')
    assert result.layout=='single_view' and result.views==[] and result.selected_index==-1
    assert provider.chat.await_count==1


@pytest.mark.asyncio
async def test_failed_preparation_is_not_cached_or_exposed(monkeypatch,tmp_path):
    monkeypatch.setattr(identity,'CONTEXT_DIR',tmp_path)
    monkeypatch.setattr(identity,'inspect_identity_sheet',AsyncMock(side_effect=RuntimeError('SECRET')))
    with pytest.raises(identity.ReferenceViewError) as caught:
        await identity.isolated_identity_view(pixels(),ImageReferenceContext(role='identity'),'target','key')
    assert 'SECRET' not in str(caught.value) and not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_reference_preparation_endpoint_identifies_no_media_submission(monkeypatch):
    import httpx
    from agent.aigc import creation
    from agent.main import app
    from tests.test_creation import request
    monkeypatch.setattr(creation,'execute_node',AsyncMock(side_effect=identity.ReferenceViewError()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/agent/creation/node',json=request().model_dump())
    assert response.status_code==400 and response.json()['detail']=={'code':'media_reference_view_failed','provider_task_id':''}


@pytest.mark.asyncio
async def test_invalid_pixels_do_not_open_a_provider_client(monkeypatch):
    factory=AsyncMock(side_effect=AssertionError('must validate pixels before opening network client'))
    monkeypatch.setattr(identity,'create_provider',factory)
    with pytest.raises(Exception):
        await identity.inspect_identity_sheet('data:image/png;base64,bm90LWltYWdl',ImageReferenceContext(role='identity'),'side')
    assert not factory.called
