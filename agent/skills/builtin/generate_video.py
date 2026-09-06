from __future__ import annotations

import uuid

from agent.aigc.spark_client import SparkProviderError
from agent.aigc.video_service import generate_video
from agent.schemas.aigc import VIDEO_MAX_FRAMES, VIDEO_NATIVE_FPS, VideoGenerationRequest
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class GenerateVideoSkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="generate_video",
            description=("AI 生视频: generate one MP4 with native audio from text using Spark. "
                         "Default 864×480, 124 native frames (~5.17s), output 24 FPS. "
                         "Dimensions: 32–4096, multiples of 32; width*height <= 1032192. "
                         "Choose num_frames OR duration_seconds; native frames round UP to 17k+5 at 24 FPS. "
                         "width*height*aligned_native_frames <= 373653504. Lower resolution permits longer clips; "
                         "124–362 native frames are suggested starting points, longer clips are experimental. "
                         "Output FPS 1–120 (up to 3 decimals) duplicates/drops frames without changing motion speed "
                         "or audio timing; it does not interpolate motion. "
                         "Preserve explicit user width×height exactly: portrait 480×864 means width=480, height=864. "
                         "Never swap dimensions or claim rotation makes a landscape result equivalent to portrait. "
                         "Describe motion, camera and sound in prompt. Text-to-video only: no reference images, "
                         "negative prompt or model choice. Return the actual video link; use response video metadata "
                         "for resolved duration/frame counts and seed_text for exact 64-bit seed. "
                         "Generation can take several minutes. A wait_timeout does not cancel the task; "
                         "resume with exactly the original prompt/options and returned idempotency_key, never a new key."),
            parameters=[
                SkillParameter(name="prompt", type="string", description="Exact scene, motion, camera and sound prompt.",
                               min_length=1, max_length=4000),
                SkillParameter(name="num_frames", type="integer", description="Native frames at 24 FPS, 5–3592, rounded up to 17k+5. Exclusive with duration_seconds; omit both for 124.",
                               required=False, minimum=5, maximum=VIDEO_MAX_FRAMES),
                SkillParameter(name="duration_seconds", type="number", description="Requested seconds >0, rounded up to native frame grid (5 seconds becomes 124 frames). Exclusive with num_frames; do not send null alone.",
                               required=False, maximum=VIDEO_MAX_FRAMES / VIDEO_NATIVE_FPS),
                SkillParameter(name="width", type="integer", description="Width, multiple of 32; default 864. Area <=1032192, area*aligned native frames <=373653504.",
                               required=False, minimum=32, maximum=4096),
                SkillParameter(name="height", type="integer", description="Height, multiple of 32; default 480. Same area and frame budget as width.",
                               required=False, minimum=32, maximum=4096),
                SkillParameter(name="fps", type="number", description="Output FPS 1–120, at most 3 decimal places (e.g. 29.97); default 24. Resamples frames, not motion interpolation.",
                               required=False, minimum=1, maximum=120),
                SkillParameter(name="seed", type="string", description="0–18446744073709551615 as a decimal string (recommended for exact precision) or integer. Omit, null or integer -1 for random; never use a floating-point seed.",
                               required=False),
                SkillParameter(name="idempotency_key", type="string", description="Reuse returned key and original input to resume.",
                               required=False, min_length=1, max_length=128),
            ],
            tags=["video", "generation"], domains=["video"],
            routing_keywords=["生视频", "生成视频", "制作视频", "文生视频", "generate video", "text to video"],
            allowed_agents=["super_chat"], always_on=True, risk_level="medium", access="external",
            max_calls_per_run=4, timeout_seconds=570, sensitive_arguments=["prompt"],
        )

    def to_tool_definition(self) -> dict:
        definition = super().to_tool_definition()
        properties = definition["parameters"]["properties"]
        # The generic metadata has one display type; the callable schema accepts both seed forms.
        properties["seed"]["anyOf"] = VideoGenerationRequest.model_json_schema()["properties"]["seed"]["anyOf"]
        properties["seed"].pop("type")
        properties["width"]["multipleOf"] = 32
        properties["height"]["multipleOf"] = 32
        properties["fps"]["multipleOf"] = .001
        properties["duration_seconds"]["exclusiveMinimum"] = 0
        return definition

    async def prepare_arguments(self, **kwargs) -> dict:
        request = VideoGenerationRequest(**kwargs)
        arguments = request.model_dump(exclude_none=True)
        arguments["idempotency_key"] = request.idempotency_key or str(uuid.uuid4())
        return arguments

    async def execute(self, **kwargs) -> SkillResult:
        try:
            arguments = await self.prepare_arguments(**kwargs)
            response = await generate_video(VideoGenerationRequest(**arguments))
            return SkillResult(success=True, data=response.model_dump(),
                display_text="\n".join(f"[AI 生视频 {video.index + 1}]({video.url})" for video in response.videos))
        except SparkProviderError as exc:
            return SkillResult(success=False, error=str(exc), error_code=exc.code, data=exc.context())
        except ValueError as exc:
            return SkillResult(success=False, error=str(exc), error_code="invalid_request")
