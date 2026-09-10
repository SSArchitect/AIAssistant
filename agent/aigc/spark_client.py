"""Spark Media Provider v1: idempotent submission, polling and authenticated download."""
from __future__ import annotations

import asyncio
import base64
import hashlib
from math import gcd, isfinite
import struct
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from agent.aigc.progress import BACKGROUND_TIMEOUT, background_enabled, emit_progress
from agent.schemas.aigc import GeneratedImage, ImageGenerationRequest, ImageGenerationResponse
from agent.aigc.image_inputs import decode_image_data_url

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "web/static/generated/aigc"
PENDING = {"submitting", "queued", "running", "recovering"}
RETRYABLE = {429, 502, 503, 504}
# Exact ratios aligned to the Provider v0.2 dimension and pixel limits.
ASPECT_SIZES = {
    "1:1": (1024, 1024), "16:9": (1536, 864), "4:3": (1152, 864),
    "3:2": (1536, 1024), "2:3": (1024, 1536), "3:4": (864, 1152),
    "9:16": (864, 1536), "21:9": (1792, 768),
}


class SparkProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "provider_error", task_id: str | None = None,
                 idempotency_key: str | None = None):
        super().__init__(message)
        self.code = code
        self.task_id = task_id
        self.idempotency_key = idempotency_key

    def context(self) -> dict:
        return {"code": self.code, "task_id": self.task_id, "idempotency_key": self.idempotency_key}


class SparkTaskClient:
    """Shared transport, idempotency and task lifecycle for Spark media clients."""

    def __init__(self, base_url: str, api_key: str, *, output_dir: Path = OUTPUT_DIR,
                 timeout: float = 240, poll_interval: float = 2,
                 transport: httpx.AsyncBaseTransport | None = None):
        if not base_url.strip():
            raise ValueError("Spark base URL not configured")
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                parsed.path not in {"", "/"}):
            raise ValueError("Spark base_url must be an HTTP(S) origin without /v1")
        if not api_key.strip():
            raise ValueError("Spark API key not configured")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.output_dir = Path(output_dir)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.transport = transport
        self._task_ids: dict[str, str] = {}

    async def _request(self, client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
        for attempt in range(3):
            try:
                response = await client.request(method, path, **kwargs)
            except httpx.TransportError:
                if attempt == 2:
                    raise SparkProviderError("Spark connection failed; retry with the original idempotency key",
                                             code="connection_failed") from None
            else:
                if response.status_code not in RETRYABLE or attempt == 2:
                    if not response.is_success:
                        code = "http_error"
                        if response.headers.get("content-type", "").split(";")[0] == "application/json":
                            try:
                                body = response.json()
                                if isinstance(body, dict) and isinstance(body.get("error"), dict):
                                    code = str(body["error"].get("code") or code)
                            except ValueError:
                                pass
                        # Never surface proxy HTML or response text that could echo credentials.
                        raise SparkProviderError(f"Spark HTTP {response.status_code} ({code})", code=code)
                    return response
            await asyncio.sleep(0.5 * (2 ** attempt))
        raise AssertionError("unreachable")

    @staticmethod
    def _task(response: httpx.Response) -> dict:
        try:
            if response.headers.get("content-type", "").split(";")[0] != "application/json":
                raise ValueError()
            task = response.json()
            if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"]:
                raise ValueError()
            if task.get("status") not in PENDING | {"failed", "succeeded", "expired"}:
                raise ValueError()
            return task
        except (ValueError, TypeError):
            raise SparkProviderError("Spark returned an invalid task response", code="invalid_response") from None

    async def generate(self, request):
        payload = self.payload(request)
        key = request.idempotency_key or str(uuid.uuid4())
        background = background_enabled()
        deadline = asyncio.get_running_loop().time() + (BACKGROUND_TIMEOUT if background else self.timeout)
        self._report(payload, key, "submitting")
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                try:
                    result = await asyncio.wait_for(self._generate(request, payload, key), min(self.timeout, max(0, remaining)))
                    self._report(payload, key, "completed")
                    return result
                except asyncio.TimeoutError:
                    if background and asyncio.get_running_loop().time() < deadline:
                        self._report(payload, key, "reconnecting")
                        continue
                    raise SparkProviderError(
                        "Spark wait timed out; the task may still be running. Retry the original input and idempotency key.",
                        code="wait_timeout", task_id=self._task_ids.get(key), idempotency_key=key,
                    ) from None
                except SparkProviderError as exc:
                    if (background and exc.code in {"connection_failed", "download_failed"}
                            and asyncio.get_running_loop().time() + 5 < deadline):
                        self._report(payload, key, "reconnecting")
                        await asyncio.sleep(5)
                        continue
                    raise
        except SparkProviderError as exc:
            exc.idempotency_key = key
            exc.task_id = exc.task_id or self._task_ids.get(key)
            uncertain = exc.code in {"wait_timeout", "connection_failed", "download_failed"}
            self._report(payload, key, "unknown" if uncertain else "failed", code=exc.code)
            raise
        finally:
            self._task_ids.pop(key, None)

    def _report(self, payload, key, stage, **extra):
        emit_progress(kind=payload["type"], stage=stage, task_id=self._task_ids.get(key),
            idempotency_key=key, **extra)


    @staticmethod
    def task_metrics(task: dict) -> dict:
        # Only explicitly scaled fields are supported. Never guess whether an
        # opaque "progress" value is a fraction, percentage or completed steps.
        metrics = {}
        position = task.get("queue_position")
        if type(position) is int and 1 <= position <= 9007199254740991:
            metrics["queue_position"] = position
        percent = task.get("progress_percent")
        if type(percent) in {int, float} and 0 <= percent <= 100 and isfinite(percent):
            metrics["progress_percent"] = percent
        return metrics

    async def _wait_for_task(self, client: httpx.AsyncClient, payload: dict, key: str) -> dict:
        known_id = self._task_ids.get(key)
        if known_id:
            task = self._task(await self._request(client, "GET", "/v1/tasks/" + quote(known_id, safe=""), timeout=30))
            if task["id"] != known_id:
                raise SparkProviderError("Spark returned a different task id", code="invalid_response")
        else:
            task = self._task(await self._request(client, "POST", "/v1/tasks", json=payload,
                                                 headers={"Idempotency-Key": key}))
        task_id = task["id"]
        self._task_ids[key] = task_id
        task_path = "/v1/tasks/" + quote(task_id, safe="")
        previous_status = (task["status"], self.task_metrics(task))
        self._report(payload, key, task["status"], **previous_status[1])
        while task["status"] in PENDING:
            await asyncio.sleep(self.poll_interval)
            task = self._task(await self._request(client, "GET", task_path, timeout=30))
            if task["id"] != task_id:
                raise SparkProviderError("Spark returned a different task id", code="invalid_response")
            next_status = (task["status"], self.task_metrics(task))
            if next_status != previous_status:
                previous_status = next_status
                self._report(payload, key, task["status"], **next_status[1])
        if task["status"] == "failed":
            error = task.get("error") or {}
            code = str(error.get("code", "generation_failed")) if isinstance(error, dict) else "generation_failed"
            raise SparkProviderError(f"Spark generation failed ({code})", code=code)
        if task["status"] == "expired":
            raise SparkProviderError("Spark artifact expired", code="artifact_expired")
        self._report(payload, key, "saving")
        return task

    async def _prepare_image_input(self, client, request, payload, key):
        if not payload.get("mode", "").startswith("image_to_"):
            return
        asset_field = "image_asset_id" if payload["type"] == "image" else "first_frame_asset_id"
        data_field = "image_data_url" if payload["type"] == "image" else "first_frame_data_url"
        if payload["input"].get(asset_field):
            return
        value = getattr(request, data_field, None)
        if not value:
            raise ValueError("Image input mode requires an asset ID or a resolved image attachment")
        content, media_type = decode_image_data_url(value)
        # Stable across process restarts; changed bytes with the same task key conflict.
        upload_key = "input-" + hashlib.sha256(key.encode()).hexdigest()
        self._report(payload, key, "uploading")
        response = await self._request(client, "POST", "/v1/assets", content=content,
            headers={"Content-Type": media_type, "Idempotency-Key": upload_key})
        try:
            asset = response.json()
            asset_id = asset["id"]
            if str(uuid.UUID(asset_id)) != asset_id or asset.get("status") not in {"ready", "expired"}:
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError):
            raise SparkProviderError("Spark returned an invalid image asset", code="invalid_response") from None
        # Expired upload replays are valid: the following task POST may resume an existing task.
        payload["input"][asset_field] = asset_id


class SparkImageClient(SparkTaskClient):
    @staticmethod
    def dimensions(request: ImageGenerationRequest) -> tuple[int, int]:
        # Explicit dimensions win over aspect_ratio; never resize a caller's requested dimensions.
        width, height = ((request.width, request.height) if request.width is not None
                         else ASPECT_SIZES[request.aspect_ratio])
        if (not 256 <= width <= 4096 or not 256 <= height <= 4096 or
                width % 16 or height % 16 or not 262144 <= width * height <= 4194304):
            raise ValueError("Spark dimensions must be 256–4096, multiples of 16, with 262144–4194304 total pixels")
        return width, height

    @staticmethod
    def payload(request: ImageGenerationRequest) -> dict:
        width, height = SparkImageClient.dimensions(request)
        if request.n != 1:
            raise ValueError("Spark currently supports one image per task (n=1)")
        if request.model or request.style or request.subject_reference or request.aigc_watermark:
            raise ValueError("Spark does not support model selection, style, MiniMax subject_reference or watermark options; use image_asset_id or image_data_url for image input")
        payload = {"type": "image", "input": {
            "prompt": request.prompt, "negative_prompt": request.negative_prompt,
            "width": width, "height": height, "seed": request.seed,
        }}
        if request.mode == "image_to_image":
            payload["mode"] = request.mode
            payload["input"].update(denoise=request.denoise if request.denoise is not None else .45,
                image_fit=request.image_fit or "center_crop")
            if request.image_asset_id:
                payload["input"]["image_asset_id"] = request.image_asset_id
        return payload

    async def _generate(self, request: ImageGenerationRequest, payload: dict, key: str) -> ImageGenerationResponse:
        async with httpx.AsyncClient(base_url=self.base_url, headers={"Authorization": f"Bearer {self.api_key}"},
                                     timeout=httpx.Timeout(60, connect=10), follow_redirects=False,
                                     transport=self.transport) as client:
            await self._prepare_image_input(client, request, payload, key)
            task = await self._wait_for_task(client, payload, key)
            task_id = task["id"]
            task_path = "/v1/tasks/" + quote(task_id, safe="")
            artifacts = task.get("artifacts")
            if not isinstance(artifacts, list) or len(artifacts) != 1:
                raise SparkProviderError("Spark returned no single image artifact", code="invalid_output")
            artifact = artifacts[0]
            path = artifact.get("download_url", "") if isinstance(artifact, dict) else ""
            parsed = urlsplit(path)
            # Credentials must stay on the configured origin and the accepted task's artifact route.
            if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or
                    not parsed.path.startswith(task_path + "/artifacts/") or
                    artifact.get("media_type") != "image/png"):
                raise SparkProviderError("Spark returned an invalid artifact URL or media type", code="invalid_output")
            width, height = payload["input"]["width"], payload["input"]["height"]
            content = await self._download(client, path, expected_size=(width, height))
            if request.response_format == "base64":
                image = GeneratedImage(index=0, base64=base64.b64encode(content).decode("ascii"))
            else:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                filename = "spark-" + uuid.uuid4().hex + ".png"
                target = self.output_dir / filename
                temporary = target.with_suffix(".part")
                try:
                    temporary.write_bytes(content)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
                image = GeneratedImage(index=0, url="/static/generated/aigc/" + filename)
            return ImageGenerationResponse(id=task_id, provider="spark", model="z-image-base",
                prompt=request.prompt, aspect_ratio=f"{width // gcd(width, height)}:{height // gcd(width, height)}",
                response_format=request.response_format,
                images=[image], metadata={"seed": task.get("seed"), "idempotency_key": key,
                                         "width": width, "height": height,
                                         **({"mode": task.get("mode") or payload.get("mode"), "source": task.get("source")}
                                            if payload.get("mode") else {})})

    async def _download(self, client: httpx.AsyncClient, path: str, *, expected_size: tuple[int, int]) -> bytes:
        # Stream with a size bound; retry a broken transfer from its beginning.
        for attempt in range(3):
            try:
                async with client.stream("GET", path) as response:
                    if response.status_code in RETRYABLE:
                        raise httpx.ReadError("Retryable download status")
                    if response.status_code != 200:
                        raise SparkProviderError(f"Spark download HTTP {response.status_code}", code="download_failed")
                    if response.headers.get("content-type", "").split(";")[0] != "image/png":
                        raise SparkProviderError("Spark download is not PNG", code="invalid_output")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 32 * 1024 * 1024:
                            raise SparkProviderError("Spark image exceeds 32 MiB", code="invalid_output")
                    if (len(content) < 33 or content[:8] != b"\x89PNG\r\n\x1a\n" or
                            content[12:16] != b"IHDR" or struct.unpack(">II", content[16:24]) != expected_size or
                            content[-12:] != b"\x00\x00\x00\x00IEND\xaeB`\x82"):
                        raise SparkProviderError(f"Spark returned an incomplete or invalid {expected_size[0]}×{expected_size[1]} PNG", code="invalid_output")
                    return bytes(content)
            except httpx.TransportError:
                if attempt == 2:
                    raise SparkProviderError("Spark image download failed", code="download_failed") from None
            await asyncio.sleep(0.5 * (2 ** attempt))
        raise AssertionError("unreachable")
