"""Creation node contract tests. Never submit billable provider requests."""
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from agent.aigc import creation

PNG = 'data:image/png;base64,' + base64.b64encode(b'png-test').decode()

def request(**kw):
    return creation.CreationNodeRequest(kind='image', prompt='test', idempotency_key='run-node', **kw)

@pytest.mark.asyncio
async def test_image_node_uses_shared_service_and_returns_durable_bytes(monkeypatch):
    generate = AsyncMock(return_value=SimpleNamespace(id='provider-1', images=[SimpleNamespace(base64=PNG.split(',')[1], mime_type='image/png')]))
    monkeypatch.setattr(creation, 'generate_image', generate)
    result = await creation.execute_node(request(input_images=[PNG], character_style='anime'))
    sent = generate.call_args.args[0]
    assert sent.provider == 'spark' and sent.mode == 'character_stylization'
    assert sent.image_data_url == PNG and sent.idempotency_key == 'run-node'
    assert result == dict(content=PNG.split(',')[1], mime_type='image/png', provider_task_id='provider-1')

@pytest.mark.asyncio
@pytest.mark.parametrize('inputs,mode', [([], None), ([PNG], 'image_to_video'), ([PNG, PNG + 'AA'], 'reference_to_video')])
async def test_video_node_routes_zero_one_and_multiple_images(monkeypatch, tmp_path, inputs, mode):
    # Use two valid distinct data URLs in the multi-reference case.
    if len(inputs) == 2: inputs[1] = 'data:image/png;base64,' + base64.b64encode(b'other').decode()
    path = tmp_path / 'result.mp4'; path.write_bytes(b'mp4-content')
    monkeypatch.setattr(creation, 'OUTPUT_DIR', tmp_path)
    generate = AsyncMock(return_value=SimpleNamespace(id='video-1', videos=[SimpleNamespace(url='/static/generated/aigc/result.mp4')]))
    monkeypatch.setattr(creation, 'generate_video', generate)
    result = await creation.execute_node(creation.CreationNodeRequest(kind='video', prompt='motion', input_images=inputs, idempotency_key='key', aspect_ratio='9:16'))
    sent = generate.call_args.args[0]
    assert sent.mode == mode and (sent.width, sent.height) == (480, 864)
    if len(inputs) == 2: assert sent.reference_image_data_urls == inputs
    assert base64.b64decode(result['content']) == b'mp4-content'

@pytest.mark.parametrize('options', [dict(input_images=[PNG, PNG]), dict(character_style='anime'), dict(input_images=['https://private.test']), dict(duration_seconds=99)])
def test_invalid_inputs_rejected_before_generation(options):
    with pytest.raises(ValidationError): request(**options)

@pytest.mark.asyncio
async def test_video_path_cannot_escape_output_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(creation, 'OUTPUT_DIR', tmp_path)
    monkeypatch.setattr(creation, 'generate_video', AsyncMock(return_value=SimpleNamespace(id='x', videos=[SimpleNamespace(url='/static/generated/aigc/../secret.mp4')])) )
    with pytest.raises(ValueError, match='路径'):
        await creation.execute_node(creation.CreationNodeRequest(kind='video', prompt='motion', idempotency_key='key'))

@pytest.mark.asyncio
async def test_creation_api_contract_and_safe_failure(monkeypatch):
    from agent.main import app
    monkeypatch.setattr(creation, 'execute_node', AsyncMock(return_value={'content': 'abc', 'mime_type': 'image/png', 'provider_task_id': 'job'}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/agent/creation/node', json=request().model_dump())
        assert response.status_code == 200 and response.json()['provider_task_id'] == 'job'
        bad = await client.post('/agent/creation/node', json={'kind': 'other'})
        assert bad.status_code == 422
        monkeypatch.setattr(creation, 'execute_node', AsyncMock(side_effect=RuntimeError('SECRET-KEY')))
        failed = await client.post('/agent/creation/node', json=request().model_dump())
        assert failed.status_code == 502 and 'SECRET' not in failed.text


@pytest.mark.asyncio
async def test_single_identity_reference_does_not_become_a_first_frame(monkeypatch, tmp_path):
    from tests.test_creation_planning import plan, request as planning_request
    from agent.aigc.creation_planning import parse_proposal
    import json
    node = parse_proposal(json.dumps(dict(reply='review', plan=plan('identity'))), planning_request()).plan.nodes[-1]
    (tmp_path / 'result.mp4').write_bytes(b'mp4-content')
    monkeypatch.setattr(creation, 'OUTPUT_DIR', tmp_path)
    generate = AsyncMock(return_value=SimpleNamespace(id='video-1', videos=[SimpleNamespace(url='/static/generated/aigc/result.mp4')]))
    monkeypatch.setattr(creation, 'generate_video', generate)
    options = dict(kind='video', prompt=node.prompt, storyboard=node.storyboard, video_mode='reference_to_video', input_images=[PNG], idempotency_key='reviewed')
    await creation.execute_node(creation.CreationNodeRequest(**options))
    sent = generate.call_args.args[0]
    assert sent.mode == 'reference_to_video' and sent.first_frame_data_url is None
    options['prompt'] = 'changed after approval'
    with pytest.raises(ValueError, match='不一致'): await creation.execute_node(creation.CreationNodeRequest(**options))
    assert generate.await_count == 1
