"""Video direction, deterministic compilation and replay; no live generation."""
import copy
import json
from unittest.mock import AsyncMock, patch

import pytest

from agent.aigc.spark_video_client import SparkVideoClient
from agent.orchestrator.context_builder import ContextBuilder
from agent.schemas.aigc import VideoGenerationRequest
from agent.schemas.chat import ChatRequest
from agent.schemas.memory import MemoryContext, RoleProfile
from agent.skills.builtin.generate_video import GenerateVideoSkill
from tests.test_spark_video import video_response


def storyboard():
    return {
        "style": "Watercolor animation with soft morning light.",
        "shots": [
            {"start_seconds": 0, "description": "A red paper crane rests on a desk. Its wings lift, then settle. The camera slowly pushes in a short distance."},
            {"start_seconds": 3.125, "description": 'The camera cuts to the window. A woman (S1) says: <d>[Chinese] 早上好，纸鹤！</d> A sign reads "春天".'},
        ],
        "overall_soundscape": "Rain taps on the window; paper softly rustles.",
        "non_diegetic_music": "N/A",
    }


def reference_storyboard():
    plan = storyboard()
    plan.update(
        subject_definitions="<Subject 1> is the red paper crane from <Picture 1>.\n<Subject 2> is the window and desk from <Picture 2>.",
        summary="[reference generation] <Subject 1> moves beside the window in <Subject 2>.",
        retention_analysis="<Subject 1> (appears in [Shot 1]): fully_preserved - red folded wings.\n<Subject 2> (appears in [Shot 1], [Shot 2]): fully_preserved - desk and window layout.",
    )
    plan["shots"][0]["description"] = "<Subject 1> lifts its red folded wings on the desk in <Subject 2>. The camera holds still."
    return plan


@pytest.mark.asyncio
async def test_storyboard_compiles_exact_sections_timing_and_original_dialogue():
    plan = storyboard()
    original = copy.deepcopy(plan)
    skill = GenerateVideoSkill()
    prepared = await skill.prepare_arguments(storyboard=plan, duration_seconds=5, fps=60, seed="18446744073709551615")
    prompt = prepared["prompt"]
    assert prompt.startswith("integrated_multimodal_description: [Shot 1] Watercolor animation")
    assert "[Shot 1] At" not in prompt
    assert "[Shot 2] At 00:03.125, The camera cuts" in prompt
    assert '<d>[Chinese] 早上好，纸鹤！</d>' in prompt
    assert '"春天"' in prompt
    assert prompt.endswith("overall_soundscape: Rain taps on the window; paper softly rustles.\n\nnon_diegetic_music: N/A")
    assert "storyboard" not in prepared
    assert prepared["duration_seconds"] == 5 and "num_frames" not in prepared
    assert prepared["seed"] == "18446744073709551615"
    assert await skill.prepare_arguments(**prepared) == prepared
    assert plan == original
    payload = SparkVideoClient.payload(VideoGenerationRequest(**prepared))
    assert payload["input"]["prompt"] == prompt
    assert "storyboard" not in payload["input"]


@pytest.mark.asyncio
async def test_first_frame_plan_is_anchored_and_raw_prompt_is_unchanged():
    skill = GenerateVideoSkill()
    prepared = await skill.prepare_arguments(storyboard=storyboard(), image_attachment_index=2)
    assert prepared["mode"] == "image_to_video"
    assert prepared["prompt"].startswith("For the target video, at 0.00 seconds")
    assert "<Picture 1> (from [Shot 1])" in prepared["prompt"]
    original = "  已经写好的提示词\n不改中文或空格。  "
    assert (await skill.prepare_arguments(prompt=original))["prompt"] == original


@pytest.mark.asyncio
async def test_reference_plan_uses_six_sections_and_selection_order():
    result = await GenerateVideoSkill().prepare_arguments(
        storyboard=reference_storyboard(), reference_image_attachment_indices=[3, 1], duration_seconds=5)
    prompt = result["prompt"]
    sections = ["subject_definitions:", "summary:", "retention_analysis:", "detailed_description:", "overall_soundscape:", "non_diegetic_music:"]
    assert [prompt.index(section) for section in sections] == sorted(prompt.index(section) for section in sections)
    assert "detailed_description: Watercolor animation with soft morning light.\n[Shot 1]" in prompt
    assert result["reference_image_attachment_indices"] == [3, 1]
    assert "integrated_multimodal_description" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("starts", [[1], [0, 0], [0, 4, 3], [0, 5], [0, 5.1], [0, -1], [0, True], [0, "3"], [0, float("nan")], [0, 1.0001]])
async def test_invalid_cut_times_fail_before_generation(starts):
    plan = storyboard()
    plan["shots"] = [{"start_seconds": start, "description": "A crane turns."} for start in starts]
    with patch("agent.skills.builtin.generate_video.generate_video", new=AsyncMock()) as generate:
        result = await GenerateVideoSkill().execute(storyboard=plan, duration_seconds=5)
    assert not result.success and result.error_code == "invalid_request"
    generate.assert_not_called()


@pytest.mark.asyncio
async def test_native_frame_duration_is_independent_of_output_fps():
    plan = storyboard()
    plan["shots"][1]["start_seconds"] = 5.1
    for fps in (12, 60):
        prepared = await GenerateVideoSkill().prepare_arguments(storyboard=plan, num_frames=120, fps=fps)
        assert "At 00:05.100" in prepared["prompt"]
    plan["shots"][1]["start_seconds"] = 5.167
    with pytest.raises(ValueError, match="duration"):
        await GenerateVideoSkill().prepare_arguments(storyboard=plan, num_frames=120)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"shots": []}, {"style": " "}, {"overall_soundscape": "\n"},
    {"unknown_field": "x"}, {"shots": [{"start_seconds": 0, "description": "[Shot 2] Extra shot."}]},
    {"shots": [{"start_seconds": 0, "description": "Use <Picture 1>."}]},
    {"shots": [{"start_seconds": 0, "description": "Use <Audio 1>."}]},
    {"shots": [{"start_seconds": 0, "description": "Continue <Video 1>."}]},
    {"shots": [{"start_seconds": 0, "description": "<Subject 1> turns."}]},
    {"shots": [{"start_seconds": 0, "description": "She says <d>[Chinese] 你好"}]},
    {"shots": [{"start_seconds": 0, "description": "She says <d>你好</d>"}]},
    {"summary": "[reference generation] Unexpected reference fields."},
])
async def test_invalid_storyboard_content_is_rejected(change):
    with pytest.raises(ValueError):
        await GenerateVideoSkill().prepare_arguments(storyboard=storyboard() | change)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"subject_definitions": None}, {"retention_analysis": " "},
    {"summary": "[video editing] Edit a source video."},
    {"summary": "[reference generation] <Subject 3> enters."},
    {"summary": "[reference generation] Use <Picture 3>."},
    {"subject_definitions": "<Subject 1> comes from <Picture 1>."},
    {"retention_analysis": "<Subject 1>: fully_preserved - red wings."},
    {"retention_analysis": "<Subject 1>: fully_preserved - wings in [Shot 3].\n<Subject 2>: fully_preserved - desk."},
])
async def test_reference_plan_rejects_missing_or_unbound_labels(change):
    with pytest.raises(ValueError):
        await GenerateVideoSkill().prepare_arguments(storyboard=reference_storyboard() | change, reference_image_attachment_indices=[1, 2])


@pytest.mark.asyncio
async def test_prompt_inputs_are_exclusive_and_never_silently_truncated():
    skill = GenerateVideoSkill()
    for inputs in ({}, {"prompt": "raw", "storyboard": storyboard()}, {"storyboard": None}):
        with pytest.raises(ValueError):
            await skill.prepare_arguments(**inputs)
    plan = storyboard()
    plan["shots"][0]["description"] = "x" * 3900
    with pytest.raises(ValueError, match="4000"):
        await skill.prepare_arguments(storyboard=plan)


@pytest.mark.asyncio
async def test_silence_is_distinct_from_no_music_and_does_not_add_an_audio_switch():
    plan = storyboard()
    plan["overall_soundscape"] = "N/A"
    with pytest.raises(ValueError, match="silence"):
        await GenerateVideoSkill().prepare_arguments(storyboard=plan)
    plan["shots"] = plan["shots"][:1]
    prepared = await GenerateVideoSkill().prepare_arguments(storyboard=plan)
    assert prepared["prompt"].endswith("overall_soundscape: N/A\n\nnon_diegetic_music: N/A")
    assert "audio" not in SparkVideoClient.payload(VideoGenerationRequest(**prepared))["input"]
    plan["non_diegetic_music"] = "A slow piano score."
    with pytest.raises(ValueError, match="silence"):
        await GenerateVideoSkill().prepare_arguments(storyboard=plan)


@pytest.mark.asyncio
async def test_dialogue_crossing_cuts_keeps_complete_blocks_and_continuity_markers():
    plan = storyboard()
    plan["shots"][0]["description"] = "A woman (S1) says: <d>[Chinese] 早上好，"
    plan["shots"][1]["description"] = "纸鹤！</d>"
    with pytest.raises(ValueError, match="close every"):
        await GenerateVideoSkill().prepare_arguments(storyboard=plan)
    plan["shots"][0]["description"] = "A woman (S1) says: <d>[Chinese] 早上好，<scenetrans></d> Her voice continues across the cut."
    plan["shots"][1]["description"] = "The camera cuts to the window as (S1) continues uninterrupted: <d>[Chinese] <scenetrans>纸鹤！</d>"
    prepared = await GenerateVideoSkill().prepare_arguments(storyboard=plan)
    assert prepared["prompt"].count("<scenetrans>") == 2
    assert plan["shots"][0]["description"] in prepared["prompt"]
    assert plan["shots"][1]["description"] in prepared["prompt"]


def test_tool_schema_exposes_complete_storyboard_and_redacts_it(engine):
    definition = GenerateVideoSkill().to_tool_definition()
    schema = definition["parameters"]
    assert schema["oneOf"] == [{"required": ["prompt"]}, {"required": ["storyboard"]}]
    plan = schema["properties"]["storyboard"]
    assert plan["additionalProperties"] is False
    assert plan["properties"]["shots"]["items"]["properties"]["start_seconds"]["multipleOf"] == .001
    assert "$ref" not in json.dumps(plan)
    redacted = engine._tool_arguments_for_trace("generate_video", {"storyboard": storyboard()})
    assert redacted["storyboard"] == "<redacted>"


def test_video_direction_guidance_only_appears_when_tool_is_available():
    builder = ContextBuilder(base_system_prompt="test")
    context = MemoryContext(role=RoleProfile(id="default", name="Default"))
    def render(names):
        return json.dumps(builder.build_system_prompt_parts(context, tool_names=names), ensure_ascii=False)
    prompt = render(["generate_video"])
    for rule in ("storyboard", "整体静音", "<scenetrans>", "<cutoff>", "台词", "一项主要动作", "口型", "retention_analysis", "尾帧", "不增加", "原文"):
        assert rule in prompt
    assert "storyboard" not in render([])


@pytest.mark.asyncio
async def test_governance_receives_compiled_prompt_and_freezes_it_for_resume(engine):
    request = ChatRequest(conversation_id="storyboard-resume", agent_id="super_chat", message="生成纸鹤视频")
    arguments = {"storyboard": storyboard(), "idempotency_key": "storyboard-key", "duration_seconds": 5}
    with patch("agent.skills.builtin.generate_video.generate_video", new=AsyncMock(return_value=video_response())) as generate:
        result = await engine._execute_skill_with_governance(request=request, run_id="storyboard-run", skill_name="generate_video", arguments=arguments)
        assert result.success
        original = generate.await_args.args[0]
        # Same key must ignore a newly drafted storyboard, retaining the exact compiled prompt.
        revised = storyboard()
        revised["style"] = "Claymation with harsh lighting."
        result = await engine._execute_skill_with_governance(request=request, run_id="storyboard-retry", skill_name="generate_video", arguments=arguments | {"storyboard": revised})
    assert result.success
    assert generate.await_args.args[0] == original
