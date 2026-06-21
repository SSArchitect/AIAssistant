from __future__ import annotations

import asyncio
from typing import Any

import httpx

from agent.config import runtime_config


class MiniMaxAIGCClient:
    """MiniMax image and speech helpers for future AIGC workflows."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimaxi.com",
        image_model: str = "image-01",
        speech_model: str = "speech-2.8-turbo",
        voice_id: str = "male-qn-qingse",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.image_model = image_model
        self.speech_model = speech_model
        self.voice_id = voice_id

    @classmethod
    def from_runtime_config(cls) -> "MiniMaxAIGCClient":
        return cls(
            api_key=runtime_config.minimax_api_key,
            base_url=runtime_config.minimax_aigc_base_url,
            image_model=runtime_config.minimax_image_model,
            speech_model=runtime_config.minimax_speech_model,
            voice_id=runtime_config.minimax_voice_id,
        )

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError("MiniMax API key not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str | None = None,
        aspect_ratio: str = "1:1",
        response_format: str = "url",
        n: int = 1,
        prompt_optimizer: bool = True,
        seed: int | None = None,
        width: int | None = None,
        height: int | None = None,
        aigc_watermark: bool = False,
        style: dict[str, Any] | None = None,
        subject_reference: list[dict[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_subject_reference = self._normalize_subject_references(subject_reference)
        payload: dict[str, Any] = {
            "model": model or self.image_model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "response_format": response_format,
            "n": n,
            "prompt_optimizer": prompt_optimizer,
        }
        optional_values = {
            "seed": seed,
            "width": width,
            "height": height,
            "style": style,
        }
        payload.update({key: value for key, value in optional_values.items() if value is not None})
        if normalized_subject_reference:
            payload["subject_reference"] = normalized_subject_reference
        if aigc_watermark:
            payload["aigc_watermark"] = True
        if extra:
            cleaned_extra = dict(extra)
            if "subject_reference" in cleaned_extra:
                normalized_extra_references = self._normalize_subject_references(
                    cleaned_extra.get("subject_reference")
                )
                if normalized_extra_references:
                    cleaned_extra["subject_reference"] = normalized_extra_references
                else:
                    cleaned_extra.pop("subject_reference", None)
            payload.update({key: value for key, value in cleaned_extra.items() if value is not None})
        return await self._post_json("/v1/image_generation", payload)

    async def synthesize_speech(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_id: str | None = None,
        emotion: str | None = None,
        audio_format: str = "mp3",
        sample_rate: int = 32000,
        bitrate: int = 128000,
        channel: int = 1,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        voice_setting: dict[str, Any] = {
            "voice_id": voice_id or self.voice_id,
            "speed": 1,
            "vol": 1,
            "pitch": 0,
        }
        if emotion:
            voice_setting["emotion"] = emotion

        payload: dict[str, Any] = {
            "model": model or self.speech_model,
            "text": text,
            "stream": False,
            "voice_setting": voice_setting,
            "audio_setting": {
                "sample_rate": sample_rate,
                "bitrate": bitrate,
                "format": audio_format,
                "channel": channel,
            },
            "subtitle_enable": False,
        }
        if extra:
            payload.update(extra)
        return await self._post_json("/v1/t2a_v2", payload)

    def _normalize_subject_references(
        self,
        references: list[dict[str, Any]] | None,
    ) -> list[dict[str, str]]:
        if not references:
            return []

        normalized: list[dict[str, str]] = []
        for item in references:
            if not isinstance(item, dict):
                continue
            image_file = (
                item.get("image_file")
                or item.get("image")
                or item.get("data_url")
                or item.get("url")
                or item.get("base64")
            )
            if not image_file:
                continue
            normalized.append(
                {
                    "type": "character",
                    "image_file": str(image_file),
                }
            )
            if len(normalized) >= 4:
                break
        return normalized

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        attempts = 5
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(
                        f"{self.base_url}{path}",
                        headers=self._headers(),
                        json=payload,
                    )
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code >= 500 and attempt + 1 < attempts:
                            await asyncio.sleep(0.5)
                            continue
                        body = exc.response.text[:500]
                        raise ValueError(
                            f"MiniMax request failed with HTTP {exc.response.status_code}: {body}"
                        ) from exc
                try:
                    data = response.json()
                except ValueError as exc:
                    raise ValueError("MiniMax returned a non-JSON response") from exc
                base_resp = data.get("base_resp") or {}
                if base_resp.get("status_code", 0) != 0:
                    message = base_resp.get("status_msg") or "MiniMax request failed"
                    raise ValueError(message)
                return data
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadError,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
            ):
                if attempt + 1 >= attempts:
                    raise
                await asyncio.sleep(0.5)

        raise RuntimeError("MiniMax request retry loop exited unexpectedly")
