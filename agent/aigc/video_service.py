"""Video generation uses the same Spark origin and credentials as image generation."""
from agent.aigc.spark_video_client import SparkVideoClient
from agent.config import runtime_config
from agent.schemas.aigc import VideoGenerationRequest, VideoGenerationResponse


async def generate_video(request: VideoGenerationRequest, *, resume_task_id=None) -> VideoGenerationResponse:
    client = SparkVideoClient(runtime_config.get("aigc.spark.base_url"), runtime_config.get("aigc.spark.api_key"))
    if resume_task_id:
        return await client.generate(request, resume_task_id=resume_task_id)
    if request.reference_image_urls:
        from agent.aigc.image_inputs import load_image_url
        values = [await load_image_url(url) for url in request.reference_image_urls]
        data = request.model_dump(exclude_none=True)
        data.pop('reference_image_urls')
        data['reference_image_data_urls'] = values
        request = VideoGenerationRequest.model_validate(data)
    return await client.generate(request)


async def video_task_status(task_id: str) -> dict:
    client = SparkVideoClient(runtime_config.get("aigc.spark.base_url"), runtime_config.get("aigc.spark.api_key"))
    return await client.inspect_task(task_id)
