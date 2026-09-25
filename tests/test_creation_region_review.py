import base64
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from agent.aigc.creation_image_layout import ImagePlacement


def fixture():
    def asset(ident, color, size=(576, 1024)):
        out = BytesIO()
        Image.new('RGB', size, color).save(out, format='PNG')
        return SimpleNamespace(id=ident, data_url='data:image/png;base64,' + base64.b64encode(out.getvalue()).decode())
    layout = ImagePlacement(center_x_percent=32, center_y_percent=18, subject_height_percent=4, subject_prompt='private execution instruction')
    return [asset('scene', 'blue', (864, 1536)), asset('candidate', 'red')], layout


def test_matching_before_after_crops_include_surroundings_without_new_requirements():
    from agent.aigc.creation_region_review import region_previews
    assets, layout = fixture()
    parts, meta = region_previews(assets, ['candidate'], 'scene', layout, '9:16')
    assert len(parts) == 4 and meta[0]['candidate_id'] == 'candidate'
    box = meta[0]['box']
    assert box[2] - box[0] >= 112  # twice the actual edited region, including all seams
    assert '原场景' in parts[0]['text'] and '成品' in parts[2]['text']
    assert 'private execution instruction' not in json.dumps(parts)
    for part, color in ((parts[1], (0, 0, 255)), (parts[3], (255, 0, 0))):
        image = Image.open(BytesIO(base64.b64decode(part['image_url']['url'].split(',')[1])))
        assert image.size == (512, 512) and image.getpixel((256, 256)) == color


@pytest.mark.parametrize('failure', ['missing_scene', 'broken_scene', 'missing_candidate', 'wrong_aspect'])
def test_missing_comparison_pixels_cannot_silently_be_approved(failure):
    from agent.aigc.creation_region_review import region_previews
    assets, layout = fixture()
    if failure == 'missing_scene': assets = assets[1:]
    if failure == 'broken_scene': assets[0].data_url = 'invalid'
    if failure == 'missing_candidate': assets = assets[:1]
    if failure == 'wrong_aspect':
        out = BytesIO(); Image.new('RGB', (512, 512)).save(out, format='PNG')
        assets[0].data_url = 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()
    with pytest.raises(ValueError): region_previews(assets, ['candidate'], 'scene', layout, '9:16')


@pytest.mark.asyncio
@pytest.mark.parametrize('artifact', [False, True])
@pytest.mark.parametrize('best_available', [False, True])
async def test_regional_review_receives_paired_context_but_keeps_frozen_intent(monkeypatch, artifact, best_available):
    from agent.aigc import creation_review as review
    from agent.llm.base import LLMResponse
    from tests.test_creation_review import request
    assets, layout = fixture()
    req = request(assets=[dict(id=a.id, name=a.id, mime_type='image/png', data_url=a.data_url) for a in assets], candidate_ids=['candidate'])
    req.current_plan['nodes'].append(dict(id='image', kind='image', purpose='shot_reference', title='远景', content='背侧小人物融入场景',
        prompt='draw', aspect_ratio='9:16', image_layout=[layout.model_dump()], references=[dict(asset_id='scene', role='environment')]))
    req.current_plan['nodes'][-1]['references'].append(dict(asset_id='identity', role='identity'))
    req.node_id = 'image'
    req.selection_mode = 'best_available' if best_available else ''
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(decision='select', asset_id='candidate', reason='ok')))))
    monkeypatch.setattr(review, 'create_provider', lambda: provider)
    from agent.aigc.creation_region_review import RegionSurfaceCheck
    checker = AsyncMock(return_value=RegionSurfaceCheck(visible_artifact=artifact, observation='人物周围存在矩形底色' if artifact else '自然融合'))
    monkeypatch.setattr(review, 'check_region_surface', checker)
    monkeypatch.setattr(review, 'check_rejection_criteria', AsyncMock())
    result = await review.review_creation(req)
    parts = provider.chat.call_args.args[0][1].content
    payload = json.loads(parts[0]['text'])
    assert payload['region_comparisons'][0]['reference_asset_id'] == 'scene'
    assert sum(p['type'] == 'image_url' for p in parts) == 4
    assert 'image_layout' not in payload['review_target']
    assert payload['review_target']['content'] == '背侧小人物融入场景'
    assert result.decision == ('revise' if artifact and not best_available else 'select')
    assert checker.await_count == 1  # verification cannot erase it or repeat paid inspection
    if artifact and best_available:
        assert '残余合成问题' in result.reason and '矩形底色' in result.reason
        assert result.asset_id == 'candidate' and not result.findings
    if artifact and not best_available:
        assert result.findings[0].category == 'artifact'
        assert result.findings[0].source_id == 'quality'


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['artifact', 'clean', 'incomplete', 'invalid'])
async def test_independent_surface_check_is_structured_and_preserves_failure(mode):
    from agent.aigc.creation_region_review import check_region_surface
    from agent.aigc.creation_review_evidence import ReviewEvidenceError
    from agent.llm.base import LLMResponse
    response = LLMResponse(content=json.dumps(dict(visible_artifact=mode == 'artifact', observation='comparison')), usage={'total_tokens': 7})
    if mode == 'incomplete': response.finish_reason = 'length'
    if mode == 'invalid': response.content = '{}'
    provider = SimpleNamespace(chat=AsyncMock(return_value=response))
    usage = {}
    if mode in ('incomplete', 'invalid'):
        with pytest.raises(ReviewEvidenceError): await check_region_surface(provider, [], usage)
    else:
        result = await check_region_surface(provider, [], usage)
        assert result.visible_artifact == (mode == 'artifact')
    assert usage == {'total_tokens': 7}


@pytest.mark.asyncio
async def test_bad_selected_candidate_does_not_reject_other_candidates(monkeypatch):
    from agent.aigc import creation_review as review
    from agent.aigc.creation_region_review import RegionSurfaceCheck
    from agent.llm.base import LLMResponse
    from tests.test_creation_review import request
    assets, layout = fixture()
    assets.append(SimpleNamespace(id='other', data_url=assets[1].data_url))
    req = request(assets=[dict(id=a.id,name=a.id,mime_type='image/png',data_url=a.data_url) for a in assets],candidate_ids=['candidate','other'])
    req.current_plan['nodes'].append(dict(id='image',kind='image',purpose='shot_reference',title='远景',content='融入原场景',prompt='draw',aspect_ratio='9:16',image_layout=[layout.model_dump()],references=[dict(asset_id='scene',role='environment'),dict(asset_id='identity',role='identity')]))
    req.node_id='image'
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(content=json.dumps(dict(decision='select',asset_id=i,reason='ok'))) for i in ['candidate','other']]))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    checker=AsyncMock(side_effect=[RegionSurfaceCheck(visible_artifact=True,observation='矩形底色'),RegionSurfaceCheck(visible_artifact=False,observation='融合正常')])
    monkeypatch.setattr(review,'check_region_surface',checker)
    result=await review.review_creation(req)
    assert result.decision=='select' and result.asset_id=='other'
    assert checker.await_count==2 and provider.chat.await_count==2
    assert '不能默认全部重画' in provider.chat.call_args.args[0][-1].content
