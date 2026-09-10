"""Shared image generation boundary for HTTP, agent workflows and direct tools."""
from agent.aigc.minimax_client import MiniMaxAIGCClient
from agent.aigc.spark_client import SparkImageClient
from agent.config import runtime_config
from agent.schemas.aigc import ImageGenerationRequest, ImageGenerationResponse


async def generate_image(request: ImageGenerationRequest) -> ImageGenerationResponse:
    provider = request.provider or runtime_config.get("aigc.image_provider", "minimax")
    if provider == "spark":
        client = SparkImageClient(runtime_config.get("aigc.spark.base_url"), runtime_config.get("aigc.spark.api_key"))
        return await client.generate(request)
    if provider != "minimax":
        raise ValueError(f"Unknown image provider: {provider}")
    if request.mode == "image_to_image" or request.denoise is not None or request.image_fit is not None:
        raise ValueError("These image-to-image options require provider=spark")
    if request.width is not None and not (512 <= request.width <= 2048 and 512 <= request.height <= 2048):
        raise ValueError("MiniMax width and height must be between 512 and 2048")
    if len(request.prompt) > 1500:
        raise ValueError("MiniMax prompt must be at most 1500 characters")
    if request.negative_prompt or request.idempotency_key:
        raise ValueError("MiniMax does not support negative_prompt or idempotency_key")
    client = MiniMaxAIGCClient.from_runtime_config()
    raw = await client.generate_image(request.prompt, model=request.model, aspect_ratio=request.aspect_ratio,
                                     response_format=request.response_format, n=request.n,
                                     prompt_optimizer=request.prompt_optimizer, extra=request.minimax_extra())
    return ImageGenerationResponse.from_minimax(raw, request, model=request.model or client.image_model)
