"""Video generation uses the same Spark origin and credentials as image generation."""
from agent.aigc.spark_video_client import SparkVideoClient
from agent.config import runtime_config
from agent.schemas.aigc import VideoGenerationRequest, VideoGenerationResponse


async def generate_video(request: VideoGenerationRequest) -> VideoGenerationResponse:
    client = SparkVideoClient(runtime_config.get("aigc.spark.base_url"), runtime_config.get("aigc.spark.api_key"))
    return await client.generate(request)
