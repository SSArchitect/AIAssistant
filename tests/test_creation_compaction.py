import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.aigc.creation_compaction import compact_storyboard
from agent.aigc.creation_models import PlanningConstraintError
from agent.aigc.creation_planning import compact_proposal, PlanningRequest, parse_proposal
from agent.aigc.video_prompting import VideoStoryboard, compile_storyboard
from agent.schemas.aigc import VideoGenerationRequest
from agent.llm.base import LLMResponse


def storyboard():
    return VideoStoryboard(style='Ink illustration, warm sunlight. ' * 40,
        shots=[dict(start_seconds=0., description='The rabbit walks and bows. ' * 120,
            panels=[dict(start_seconds=0., end_seconds=5., description='He smiles and bows. ' * 80 + '<d>[Chinese]你好。</d>')])],
        overall_soundscape='Soft wind.', non_diegetic_music='N/A',
        continuity_locks=['Keep his red cape.'], execution_constraints=['No subtitles.'])


def editor(break_dialogue=False):
    async def respond(messages, **kwargs):
        payload = json.loads(messages[1].content)
        values = {}
        for key, item in payload.items():
            values[key] = '兔子行走后拱手，微笑，固定机位。' if 'shots' in item['path'] else '水墨暖光，微风。'
            if '<d>' in item['text'] and not break_dialogue:
                values[key] += '<d>[Chinese]你好。</d>'
            if break_dialogue:
                values[key] += '<d>[Chinese]改掉原话。</d>'
        return LLMResponse(content=json.dumps(values), usage={'output_tokens': 10})
    return SimpleNamespace(chat=AsyncMock(side_effect=respond), max_tokens=16000)


@pytest.mark.asyncio
async def test_node_compaction_preserves_timing_rules_dialogue_and_original():
    original = storyboard()
    before = original.model_dump()
    provider = editor()
    req = VideoGenerationRequest(prompt='placeholder', duration_seconds=5)
    result, usage = await compact_storyboard(original, req, provider)
    assert len(compile_storyboard(result, req)) <= 3900
    assert result.shots[0].panels[0].start_seconds == 0 and result.shots[0].panels[0].end_seconds == 5
    assert '<d>[Chinese]你好。</d>' in result.shots[0].panels[0].description
    assert result.continuity_locks == original.continuity_locks
    assert result.execution_constraints == original.execution_constraints
    assert original.model_dump() == before and provider.max_tokens == 16000
    assert usage == {'output_tokens': 10}


@pytest.mark.asyncio
async def test_node_compaction_rejects_changed_dialogue_and_stops_after_bounded_attempts():
    provider = editor(break_dialogue=True)
    with pytest.raises(PlanningConstraintError):
        await compact_storyboard(storyboard(), VideoGenerationRequest(prompt='placeholder', duration_seconds=5), provider)
    assert provider.chat.await_count == 3 and provider.max_tokens == 16000


@pytest.mark.asyncio
async def test_compaction_keeps_review_script_and_never_edits_locked_nodes():
    plan = dict(title='故事', summary='完整剧情', questions=[], nodes=[
        dict(id='script', kind='text', purpose='script', title='脚本', content='完整中文审阅稿保持不变'),
        dict(id='video', kind='video', title='片段', depends_on=['script'], storyboard=storyboard().model_dump())])
    wire = json.dumps(dict(reply='ready', plan=plan))
    request = PlanningRequest(project_id='p', user_id='u', messages=[])
    provider = editor()
    result, _ = await compact_proposal(wire, request, provider, AsyncMock())
    parsed = parse_proposal(result, request)
    assert parsed.plan.nodes[0].content == plan['nodes'][0]['content']
    assert len(parsed.plan.nodes[1].prompt) <= 3900
    provider.chat.reset_mock()
    await compact_proposal(wire, request.model_copy(update={'locked_node_ids': ['video']}), provider, AsyncMock())
    provider.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_long_reference_rules_can_be_compacted_without_rewriting_protocol_or_dialogue():
    original = VideoStoryboard(style='Ink.',
        shots=[dict(start_seconds=0., description='<Subject 1> moves. ' * 30 + '<d>[Chinese]这是我的原话。</d>')],
        subject_definitions='<Subject 1> is a rabbit from <Picture 1>.',
        summary='[reference generation] A rabbit walks.',
        retention_analysis='<Subject 1> (appears in [Shot 1]): fully_preserved - identity.',
        reference_rules=['Keep the ink texture and exclude sheet layout. ' * 60],
        continuity_locks=['Keep the red cape and carrot sword. ' * 60],
        execution_constraints=['No added narration or subtitles.'], overall_soundscape='Wind.')
    before=original.model_dump()
    provider=editor()
    req=VideoGenerationRequest(prompt='placeholder',duration_seconds=5,reference_image_data_urls=['data:image/png;base64,eA=='])
    compacted,_=await compact_storyboard(original,req,provider)
    prompt=compile_storyboard(compacted,req)
    assert len(prompt)<=3900 and '<d>[Chinese]这是我的原话。</d>' in prompt
    assert '<Subject 1>' in compacted.subject_definitions and '<Picture 1>' in compacted.subject_definitions
    assert compacted.summary.startswith('[reference generation]')
    assert 'fully_preserved -' in compacted.retention_analysis
    assert original.model_dump()==before
    # Model rewrites prose only; literal speech and protocol are restored by code.
    payload=json.loads(provider.chat.call_args.args[0][1].content)
    assert all('<d>' not in item['text'] and '<Picture' not in item['text'] for item in payload.values())


@pytest.mark.asyncio
async def test_uncompressible_literal_text_reports_capacity_without_spending_repair_calls():
    original=VideoStoryboard(style='Ink.',overall_soundscape='Speech.',shots=[
        dict(start_seconds=0.,description='<d>[Chinese]'+('甲'*2100)+'</d>'),
        dict(start_seconds=2.,description='<d>[Chinese]'+('乙'*2100)+'</d>')])
    provider=editor()
    with pytest.raises(PlanningConstraintError) as caught:
        await compact_storyboard(original,VideoGenerationRequest(prompt='placeholder',duration_seconds=5),provider)
    assert caught.value.code=='execution_capacity_exceeded'
    provider.chat.assert_not_awaited()
