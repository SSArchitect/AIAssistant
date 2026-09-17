"""Semantic panels are reviewed and compiled as one clip, without live generation."""
import copy
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.aigc.video_prompting import VideoStoryboard, compile_storyboard
from agent.aigc.creation_planning import parse_proposal
from agent.schemas.aigc import VideoGenerationRequest
from agent.skills.builtin.generate_video import GenerateVideoSkill
from tests.test_creation_planning import request as planning_request
from tests.test_spark_video import video_response
from agent.llm.base import LLMResponse


def semantic_storyboard():
    boundaries = [0, 1.8, 3.5, 5, 6.7, 8.2, 10, 11.8, 13, 15]
    actions = [
        'High overhead: eighteen pots orbit the tired goose; the camera descends.',
        '(S1) lifts a feather boomerang: <d>[Chinese] 卑鄙……</d> Wind lowers.',
        '(S1): <d>[Chinese] 以多欺少算什么好汉！</d> A white silhouette enters above.',
        'The rabbit leaps from the roof; side tracking descends with him.',
        'He lands before the goose, between her and the pots. Dust rises; a dull impact.',
        '(S2): <d>[Chinese] 欺负一只白鹅……算什么炖锅教。</d> Hold the protective position.',
        'Low tracking angle: he leaps with the carrot sword; three front pots advance.',
        'Brief slow motion: a lateral slash releases gold ink energy. Air whistles.',
        'Three pots rise in order, with three clangs; others stay behind. He lands before her.',
    ]
    return dict(
        style='2D ink animation: dry brush, broken ink strokes, rice-paper bleed, restrained watercolor.',
        reference_rules=['<Picture 1> supplies rabbit identity; add a bamboo hat.',
                         '<Picture 2> supplies goose identity; replace the polearm with a feather boomerang.',
                         '<Picture 3> supplies cultist identity.',
                         '<Picture 4> alone defines the ink style, not an exact first frame.',
                         'Exclude turnaround layouts, labels, palettes and reference-sheet text.'],
        continuity_locks=['Rabbit stays between goose and pots after landing; keep the street axis.',
                          'Eighteen pots; only three front pots fly away. Characters retain distinct silhouettes.'],
        execution_constraints=['One continuous 15-second portrait clip in one generation, not three files.',
                               'Exact Chinese dialogue, ambient sounds and effects; no narration or subtitles.'],
        subject_definitions='<Subject 1> is rabbit from <Picture 1>.\n<Subject 2> is goose from <Picture 2>.\n<Subject 3> is cultists from <Picture 3>.\n<Picture 4> is the ink style reference.',
        summary='[reference generation] A rabbit rescues a goose and lifts three pots.',
        retention_analysis='<Subject 1> ([Shot 2], [Shot 3]): partially_preserved - identity, added hat.\n<Subject 2> ([Shot 1], [Shot 2], [Shot 3]): partially_preserved - identity, changed weapon.\n<Subject 3> ([Shot 1], [Shot 3]): fully_preserved - identity.\n<Picture 4> ([Shot 1], [Shot 2], [Shot 3]): attribute_transfer - ink medium.',
        shots=[dict(start_seconds=boundaries[g * 3], description=label, panels=[
            dict(start_seconds=boundaries[i], end_seconds=boundaries[i+1], description=actions[i])
            for i in range(g * 3, g * 3 + 3)])
            for g, label in enumerate(['Establish the siege.', 'Reveal the rescuer.', 'Resolve the action.'])],
        overall_soundscape='Wind, pot hum, Chinese voices, cloth and metal impacts.',
        non_diegetic_music='Accelerating drums with a pause for the slash.',
    )


def options():
    return VideoGenerationRequest(prompt='plan', duration_seconds=15, width=480, height=864,
                                  reference_image_attachment_indices=[3, 1, 2, 4])


@pytest.mark.asyncio
async def test_nine_semantic_panels_compile_to_three_shots_and_one_provider_submission():
    plan = semantic_storyboard(); original = copy.deepcopy(plan)
    with patch('agent.skills.builtin.generate_video.generate_video', new=AsyncMock(return_value=video_response())) as generate:
        result = await GenerateVideoSkill().execute(storyboard=plan, duration_seconds=15, width=480, height=864,
                                                    reference_image_attachment_indices=[3, 1, 2, 4])
    assert result.success
    generate.assert_awaited_once()
    sent = generate.await_args.args[0]
    prompt = sent.prompt
    assert sent.duration_seconds == 15 and sent.reference_image_attachment_indices == [3, 1, 2, 4]
    assert '[Shot 3] At 00:10.000,' in prompt and '[Shot 4]' not in prompt
    for start, end in [('00:00.000', '00:01.800'), ('00:08.200', '00:10.000'), ('00:13.000', '00:15.000')]:
        assert f'{start}–{end}' in prompt
    for key in ['reference_rules', 'continuity_locks', 'execution_constraints']:
        assert all(rule in prompt for rule in plan[key])
    assert '<d>[Chinese] 欺负一只白鹅……算什么炖锅教。</d>' in prompt
    assert len(prompt) <= 4000 and plan == original


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    lambda p: p['shots'][0]['panels'][0].update(start_seconds=.1),
    lambda p: p['shots'][0]['panels'][1].update(start_seconds=1.9),  # gap
    lambda p: p['shots'][0]['panels'][1].update(start_seconds=1.7),  # overlap
    lambda p: p['shots'][1]['panels'][0].update(end_seconds=5),     # empty
    lambda p: p['shots'][0]['panels'][-1].update(end_seconds=5.1), # crosses logical cut
    lambda p: p['shots'][-1]['panels'][-1].update(end_seconds=14), # uncovered ending
    lambda p: p['shots'][-1]['panels'][-1].update(end_seconds=16),
    lambda p: p['shots'][0]['panels'][0].update(start_seconds=True),
    lambda p: p['shots'][0]['panels'][0].update(end_seconds=1.8001),
])
async def test_panel_timeline_errors_fail_before_any_paid_submission(change):
    plan = semantic_storyboard(); change(plan)
    with patch('agent.skills.builtin.generate_video.generate_video', new=AsyncMock()) as generate:
        result = await GenerateVideoSkill().execute(storyboard=plan, duration_seconds=15,
                                                    reference_image_attachment_indices=[1, 2, 3, 4])
    assert not result.success and result.error_code == 'invalid_request'
    generate.assert_not_called()


@pytest.mark.parametrize('field,text', [
    ('reference_rules', '<Picture 5> supplies style.'),
    ('continuity_locks', '<Subject 9> keeps its red cape.'),
    ('execution_constraints', 'Use <Audio 1> exactly.'),
    ('execution_constraints', '<d>[Chinese] unfinished'),
    ('execution_constraints', '[Shot 4] holds the ending.'),
])
def test_new_locks_cannot_bypass_reference_or_dialogue_validation(field, text):
    plan = semantic_storyboard(); plan[field] = [text]
    with pytest.raises(ValueError):
        compile_storyboard(VideoStoryboard.model_validate(plan), options())


def test_new_locks_are_not_silently_dropped_to_fit_provider_limit():
    plan = semantic_storyboard(); plan['continuity_locks'] = ['x' * 3500]
    with pytest.raises(ValueError, match='4000'):
        compile_storyboard(VideoStoryboard.model_validate(plan), options())


def test_one_deliverable_with_nine_panels_survives_director_plan_and_serialization():
    board = semantic_storyboard()
    # This compact test uses text mode while preserving panel/group structure.
    for field in ['reference_rules', 'subject_definitions', 'retention_analysis', 'summary']:
        board.pop(field)
    value = dict(reply='完整15秒单次生成，先审阅', plan=dict(title='武侠短片', summary='一条完整视频', nodes=[
        dict(id='script', kind='text', purpose='script', title='语义分镜审阅', content='制作简报及九段语义分镜'),
        dict(id='video', kind='video', title='完整短片', duration_seconds=15, aspect_ratio='9:16',
             depends_on=['script'], storyboard=board)]))
    result = parse_proposal(json.dumps(value), planning_request())
    videos = [n for n in result.plan.nodes if n.kind == 'video']
    assert len(videos) == 1 and len(videos[0].storyboard.shots) == 3
    assert sum(len(s.panels) for s in videos[0].storyboard.shots) == 9
    restored = type(result).model_validate_json(result.model_dump_json())
    assert restored.plan.nodes[-1].prompt == videos[0].prompt


@pytest.mark.asyncio
async def test_creation_execution_preserves_reviewed_panels_and_locks(monkeypatch, tmp_path):
    from agent.aigc import creation
    from tests.test_creation import PNG
    board = VideoStoryboard.model_validate(semantic_storyboard())
    prompt = compile_storyboard(board, options())
    (tmp_path / 'result.mp4').write_bytes(b'mp4')
    monkeypatch.setattr(creation, 'OUTPUT_DIR', tmp_path)
    generate = AsyncMock(return_value=SimpleNamespace(id='task', videos=[SimpleNamespace(url='/static/generated/aigc/result.mp4')]))
    monkeypatch.setattr(creation, 'generate_video', generate)
    images = [PNG, *['data:image/png;base64,' + base64.b64encode(f'image{i}'.encode()).decode() for i in range(3)]]
    node = creation.CreationNodeRequest(kind='video', prompt=prompt, storyboard=board,
        duration_seconds=15, aspect_ratio='9:16', input_images=images, video_mode='reference_to_video', idempotency_key='reviewed')
    await creation.execute_node(node)
    assert generate.await_args.args[0].prompt == prompt
    node.storyboard.continuity_locks.append('Changed after approval.')
    with pytest.raises(ValueError, match='不一致'):
        await creation.execute_node(node)
    generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_creator_receives_semantic_design_skill_in_its_own_runtime(monkeypatch):
    from agent.aigc import creation_planning
    from tests.test_creation_planning import plan
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(reply='请审阅', plan=plan())))))
    monkeypatch.setattr(creation_planning, 'create_provider', lambda: provider)
    await creation_planning.propose_creation(planning_request())
    system = provider.chat.await_args.args[0][0].content
    assert '不能按编号分镜/Panel/Logical Shot的数量决定视频节点数量' in system
    assert all(section in system for section in ['制作简报', '素材贡献', '连续性锁', '主时间线', '执行锁'])
    assert '创作项目必须经过画布审阅与明确提交' in system
    assert '普通短片无需额外确认' not in system
    schema = GenerateVideoSkill().to_tool_definition()['parameters']['properties']['storyboard']
    properties = schema['properties']
    assert all(name in properties for name in ['reference_rules', 'continuity_locks', 'execution_constraints'])
    assert 'end_seconds' in properties['shots']['items']['properties']['panels']['items']['properties']


@pytest.mark.parametrize('description', ['Use <Picture 5>.', 'Use <Video 1>.', '[Shot 2] new cut.', '<d>[Chinese] 未闭合'])
def test_panel_content_obeys_the_same_media_and_dialogue_validation(description):
    plan = semantic_storyboard(); plan['shots'][0]['panels'][0]['description'] = description
    with pytest.raises(ValueError):
        compile_storyboard(VideoStoryboard.model_validate(plan), options())


def test_dialogue_inside_panels_conflicts_with_complete_silence():
    plan = semantic_storyboard(); plan.update(overall_soundscape='N/A', non_diegetic_music='N/A')
    with pytest.raises(ValueError, match='silence'):
        compile_storyboard(VideoStoryboard.model_validate(plan), options())


def test_frame_based_panels_use_millisecond_display_of_native_duration_not_output_fps():
    plan = VideoStoryboard(style='Ink.', overall_soundscape='Wind.', shots=[dict(start_seconds=0,
        description='A bird rests.', panels=[dict(start_seconds=0, end_seconds=5.167, description='It opens its wings, then rests.')])])
    for fps in (12, 60):
        request = VideoGenerationRequest(prompt='plan', num_frames=120, fps=fps)
        assert '00:00.000–00:05.167' in compile_storyboard(plan, request)
    # An explicitly requested 5s timeline still must end at 5s, not the aligned native duration.
    with pytest.raises(ValueError, match='Panels'):
        compile_storyboard(plan, VideoGenerationRequest(prompt='plan', duration_seconds=5))
