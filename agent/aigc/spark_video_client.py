"""Spark Provider 0.8 video templates with bounded, atomic MP4 downloads."""
from __future__ import annotations

import asyncio
from pathlib import Path
import struct
import uuid
from urllib.parse import quote

import httpx

from agent.aigc.spark_client import OUTPUT_DIR, RETRYABLE, SparkProviderError, SparkTaskClient
from agent.schemas.aigc import GeneratedVideo, VideoGenerationRequest, VideoGenerationResponse

MAX_VIDEO_BYTES = 512 * 1024 * 1024


class SparkVideoClient(SparkTaskClient):
    def __init__(self, base_url: str, api_key: str, *, output_dir: Path = OUTPUT_DIR,
                 timeout: float = 540, poll_interval: float = 5,
                 transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(base_url, api_key, output_dir=output_dir, timeout=timeout,
                         poll_interval=poll_interval, transport=transport)

    @staticmethod
    def payload(request: VideoGenerationRequest) -> dict:
        # Do not replace duration input with aligned frames: they are distinct idempotent requests.
        inputs = request.model_dump(exclude={"idempotency_key", "mode", "first_frame_data_url", "image_attachment_index"}, exclude_none=True)
        inputs["seed"] = request.seed
        template = "video.image.v1" if request.mode == "image_to_video" else "video.text.v1"
        payload = {"type": "video", "template": template, "input": inputs}
        if request.mode == "image_to_video":
            payload["mode"] = request.mode
            inputs["image_fit"] = request.image_fit or "center_crop"
        return payload

    @staticmethod
    def _task(response: httpx.Response) -> dict:
        task = SparkTaskClient._task(response)
        if task.get("type") != "video":
            raise SparkProviderError("Spark returned a non-video task", code="invalid_response")
        return task

    async def _generate(self, request: VideoGenerationRequest, payload: dict, key: str) -> VideoGenerationResponse:
        async with httpx.AsyncClient(base_url=self.base_url, headers={"Authorization": f"Bearer {self.api_key}"},
                                     timeout=httpx.Timeout(60, connect=10), follow_redirects=False,
                                     transport=self.transport) as client:
            await self._prepare_image_input(client, request, payload, key)
            # Replaying POST with the original key also resumes tasks when new video submissions are disabled.
            task = await self._wait_for_task(client, payload, key)
            video = task.get("video")
            if video is not None and not isinstance(video, dict):
                raise SparkProviderError("Spark returned invalid video metadata", code="invalid_response")
            artifacts = task.get("artifacts")
            if not isinstance(artifacts, list) or len(artifacts) != 1 or not isinstance(artifacts[0], dict):
                raise SparkProviderError("Spark returned no single video artifact", code="invalid_output")
            artifact = artifacts[0]
            artifact_id = artifact.get("id")
            if (not isinstance(artifact_id, str) or not artifact_id or
                    any(char in artifact_id for char in "/\\%") or artifact_id in {".", ".."}):
                raise SparkProviderError("Spark returned an invalid artifact id", code="invalid_output")
            path = f"/v1/tasks/{quote(task['id'], safe='')}/artifacts/{quote(artifact_id, safe='')}"
            if (artifact.get("download_url") != path or artifact.get("type") != "video" or
                    artifact.get("media_type") != "video/mp4"):
                raise SparkProviderError("Spark returned an invalid artifact URL or media type", code="invalid_output")
            filename = "spark-video-" + uuid.uuid4().hex + ".mp4"
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                await self._download_video(client, path, self.output_dir / filename)
            except OSError:
                raise SparkProviderError("Could not save Spark video", code="storage_failed") from None
            metadata = {"width": request.width, "height": request.height,
                        "num_frames": request.resolved_frames(), "fps": request.fps, "audio": True}
            # Provider-persisted execution parameters take precedence over local request estimates.
            metadata.update(video or {})
            metadata.update({"seed": task.get("seed"), "seed_text": task.get("seed_text"), "idempotency_key": key,
                             "template": task.get("template") or payload["template"]})
            if payload.get("mode"):
                metadata.update(mode=task.get("mode") or payload["mode"], source=task.get("source"))
            return VideoGenerationResponse(id=task["id"], prompt=request.prompt,
                videos=[GeneratedVideo(index=0, url="/static/generated/aigc/" + filename)],
                seed_text=task.get("seed_text"), video=video, metadata=metadata)

    async def _download_video(self, client: httpx.AsyncClient, path: str, target: Path) -> None:
        temporary = target.with_suffix(".part")
        try:
            for attempt in range(3):
                try:
                    async with client.stream("GET", path) as response:
                        if response.status_code in RETRYABLE:
                            raise httpx.ReadError("Retryable download status")
                        if response.status_code != 200:
                            code = "artifact_expired" if response.status_code == 410 else "download_failed"
                            raise SparkProviderError(f"Spark download HTTP {response.status_code}", code=code)
                        if response.headers.get("content-type", "").split(";")[0] != "video/mp4":
                            raise SparkProviderError("Spark download is not MP4", code="invalid_output")
                        length = response.headers.get("content-length")
                        if length is not None and (not length.isdigit() or int(length) > MAX_VIDEO_BYTES):
                            raise SparkProviderError("Spark video has an invalid or excessive size", code="invalid_output")
                        received = 0
                        # Restart from byte zero after an interrupted transfer; never append a full 200 response.
                        with temporary.open("wb") as output:
                            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                                received += len(chunk)
                                if received > MAX_VIDEO_BYTES:
                                    raise SparkProviderError("Spark video exceeds 512 MiB", code="invalid_output")
                                output.write(chunk)
                        if length is not None and received != int(length):
                            raise httpx.ReadError("Incomplete video download")
                    self._validate_mp4(temporary)
                    temporary.replace(target)
                    return
                except httpx.TransportError:
                    if attempt == 2:
                        raise SparkProviderError("Spark video download failed", code="download_failed") from None
                await asyncio.sleep(0.5 * (2 ** attempt))
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_mp4(path: Path) -> None:
        """Check complete top-level MP4 boxes without loading the video into memory.

        Codec/audio/dimension validation belongs to the Provider; metadata describes requested settings.
        """
        total = path.stat().st_size
        boxes: set[bytes] = set()
        with path.open("rb") as source:
            while source.tell() < total:
                offset = source.tell()
                header = source.read(8)
                if len(header) != 8:
                    break
                size, kind = struct.unpack(">I4s", header)
                header_size = 8
                if size == 1:
                    extended = source.read(8)
                    if len(extended) != 8:
                        break
                    size = struct.unpack(">Q", extended)[0]
                    header_size = 16
                elif size == 0:
                    size = total - offset
                if size < header_size or offset + size > total or (offset == 0 and kind != b"ftyp"):
                    break
                if kind in {b"ftyp", b"moov", b"mdat"} and size == header_size:
                    break
                boxes.add(kind)
                source.seek(offset + size)
            else:
                if {b"ftyp", b"moov", b"mdat"} <= boxes:
                    return
        raise SparkProviderError("Spark returned an incomplete or invalid MP4", code="invalid_output")
