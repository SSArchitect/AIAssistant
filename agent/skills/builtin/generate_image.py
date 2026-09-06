from __future__ import annotations

import uuid

from agent.aigc.image_service import generate_image
from agent.aigc.spark_client import SparkProviderError
from agent.config import runtime_config
from agent.schemas.aigc import IMAGE_ASPECT_RATIOS, ImageGenerationRequest
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class GenerateImageSkill(Skill):
    """Internal direct-call adapter; image_generation_v1 is the public tool."""

    auto_discover = False
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="generate_image",
            description=("Generate an image from a finished visual prompt and return renderable image URLs. "
                         "Use image_generation_v1 when research or professional prompt refinement is needed. "
                         "Spark supports one PNG: each dimension 256–4096 in multiples of 16, total pixels 262144–4194304. "
                         "After an uncertain Spark result, reuse the original input and returned idempotency_key."),
            parameters=[
                SkillParameter(name="prompt", type="string", description="Exact visual prompt.", max_length=4000),
                SkillParameter(name="provider", type="string", description="Provider; omitted uses server configuration.",
                               required=False, enum=["spark", "minimax"]),
                SkillParameter(name="negative_prompt", type="string", description="Spark negative prompt.",
                               required=False, max_length=4000),
                SkillParameter(name="width", type="integer", description="Width in pixels. Spark: 256–4096, multiple of 16; MiniMax: 512–2048, multiple of 8. Provide height too.", required=False),
                SkillParameter(name="height", type="integer", description="Height in pixels. Same per-provider limits as width; Spark total pixels 262144–4194304.", required=False),
                SkillParameter(name="aspect_ratio", type="string", description="Image ratio when width/height are omitted. Explicit dimensions take precedence.",
                               required=False, enum=sorted(IMAGE_ASPECT_RATIOS)),
                SkillParameter(name="seed", type="integer", description="Random seed; omit for random generation.",
                               required=False, minimum=0, maximum=4294967295),
                SkillParameter(name="idempotency_key", type="string", description="Spark retry key; reuse with exactly the original input.",
                               required=False, min_length=1, max_length=128),
            ],
            tags=["image", "generation"], domains=["image"],
            routing_keywords=["生图", "生成图片", "画图", "generate image", "text to image"],
            allowed_agents=["super_chat", "image_generation_v1"], risk_level="medium", access="external",
            max_calls_per_run=4, timeout_seconds=270, sensitive_arguments=["prompt", "negative_prompt"],
        )

    async def prepare_arguments(self, **kwargs) -> dict:
        allowed = {parameter.name for parameter in self.metadata().parameters}
        if set(kwargs) - allowed:
            raise ValueError("Unknown image generation parameters")
        request = ImageGenerationRequest(**kwargs)
        arguments = request.model_dump(include=allowed, exclude_none=True)
        arguments["provider"] = request.provider or runtime_config.get("aigc.image_provider", "minimax")
        if arguments["provider"] == "spark" and not request.idempotency_key:
            arguments["idempotency_key"] = str(uuid.uuid4())
        return arguments

    async def execute(self, **kwargs) -> SkillResult:
        try:
            arguments = await self.prepare_arguments(**kwargs)
            response = await generate_image(ImageGenerationRequest(**arguments))
            return SkillResult(success=True, data=response.model_dump(),
                display_text="\n".join(f"![AI 生图 {image.index + 1}]({image.url})" for image in response.images if image.url))
        except SparkProviderError as exc:
            return SkillResult(success=False, error=str(exc), error_code=exc.code, data=exc.context())
        except ValueError as exc:
            return SkillResult(success=False, error=str(exc), error_code="invalid_request")
