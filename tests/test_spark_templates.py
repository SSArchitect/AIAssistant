"""Provider 0.8 public templates through the existing Agent generation requests."""
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agent.aigc.spark_client import SparkImageClient, SparkProviderError
from agent.aigc.spark_video_client import SparkVideoClient
from agent.schemas.aigc import ImageGenerationRequest, VideoGenerationRequest
from tests.test_spark_image import png, task as image_task
from tests.test_spark_image_inputs import ASSET, DATA
from tests.test_spark_video import mp4, task as video_task


CASES = [
    ("image.text.v1", {}),
    ("image.edit.v1", {"image_data_url": DATA}),
    ("image.character.anime.v1", {"image_data_url": DATA, "character_style": "anime"}),
    ("image.character.chibi.v1", {"image_data_url": DATA, "character_style": "chibi"}),
    ("video.text.v1", {"duration_seconds": 3, "seed": str(2**64 - 1)}),
    ("video.image.v1", {"first_frame_data_url": DATA, "duration_seconds": 3}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("template,options", CASES)
@pytest.mark.parametrize("legacy_response", [False, True])
async def test_templates_submit_retry_poll_upload_and_download(tmp_path, template, options, legacy_response):
    is_video = template.startswith("video.")
    request_class = VideoGenerationRequest if is_video else ImageGenerationRequest
    client_class = SparkVideoClient if is_video else SparkImageClient
    task = video_task if is_video else image_task
    posts, uploads = [], []
    response_fields = {} if legacy_response else {"template": template}

    def handle(request):
        assert request.headers["authorization"] == "Bearer secret"
        if request.url.path == "/v1/assets":
            uploads.append(request)
            assert request.content == png(320, 240)
            return httpx.Response(201, json={"id": ASSET, "status": "ready"})
        if request.method == "POST":
            posts.append(request)
            payload = json.loads(request.content)
            assert payload["template"] == template
            assert payload["type"] == ("video" if is_video else "image")
            inputs = payload["input"]
            assert inputs["prompt"] == "  keep the subject  "
            assert "template" not in inputs
            assert "data_url" not in request.content.decode()
            if uploads:
                assert inputs["first_frame_asset_id" if is_video else "image_asset_id"] == ASSET
                assert inputs["image_fit"] == "center_crop"
            if "character_style" in options:
                assert payload["mode"] == "character_stylization"
                assert inputs["character_style"] == options["character_style"]
                assert "denoise" not in inputs
            elif template == "image.edit.v1":
                assert payload["mode"] == "image_to_image"
                assert inputs["denoise"] == .45
            elif template == "video.image.v1":
                assert payload["mode"] == "image_to_video"
            if is_video:
                assert inputs["duration_seconds"] == 3
                assert "num_frames" not in inputs and "negative_prompt" not in inputs
                assert inputs["seed"] == options.get("seed")
            if len(posts) == 1:
                raise httpx.ReadTimeout("lost create response")
            return httpx.Response(202, json=task("queued", **response_fields))
        if "/artifacts/" in request.url.path:
            return httpx.Response(200, content=mp4() if is_video else png(),
                                  headers={"Content-Type": "video/mp4" if is_video else "image/png"})
        return httpx.Response(200, json=task(**response_fields))

    client = client_class("https://spark.test", "secret", output_dir=tmp_path,
                          transport=httpx.MockTransport(handle), poll_interval=0)
    with patch("agent.aigc.spark_client.asyncio.sleep", new=AsyncMock()):
        result = await client.generate(request_class(prompt="  keep the subject  ",
                                                    idempotency_key="original-key", **options))
    assert len(posts) == 2
    assert len({post.content for post in posts}) == 1
    assert {post.headers["idempotency-key"] for post in posts} == {"original-key"}
    assert len(uploads) == int("image_data_url" in options or "first_frame_data_url" in options)
    assert result.metadata["template"] == template
    assert result.metadata["idempotency_key"] == "original-key"
    assert len(list(tmp_path.iterdir())) == 1
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.asyncio
@pytest.mark.parametrize("template,options", CASES)
@pytest.mark.parametrize("status,code", [(422, "unsupported_mode"),
                                       (422, "unsupported_task_type"), (409, "idempotency_conflict")])
async def test_template_rejection_never_falls_back_or_changes_key(tmp_path, template, options, status, code):
    is_video = template.startswith("video.")
    options = dict(options)
    for data_field, asset_field in [("image_data_url", "image_asset_id"),
                                    ("first_frame_data_url", "first_frame_asset_id")]:
        if data_field in options:
            options.pop(data_field)
            options[asset_field] = ASSET
    seen = []

    def handle(request):
        seen.append(request)
        assert request.url.path == "/v1/tasks" and request.method == "POST"
        assert json.loads(request.content)["template"] == template
        return httpx.Response(status, json={"error": {"code": code}})

    client_class = SparkVideoClient if is_video else SparkImageClient
    request_class = VideoGenerationRequest if is_video else ImageGenerationRequest
    client = client_class("https://spark.test", "secret", output_dir=tmp_path,
                          transport=httpx.MockTransport(handle))
    with pytest.raises(SparkProviderError) as error:
        await client.generate(request_class(prompt="subject", idempotency_key="original-key", **options))
    assert error.value.code == code
    assert error.value.idempotency_key == "original-key"
    assert len(seen) == 1
    assert not list(tmp_path.iterdir())
