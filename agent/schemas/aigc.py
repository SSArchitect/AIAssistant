from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


IMAGE_ASPECT_RATIOS = {"1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"}


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1500)
    model: str | None = None
    aspect_ratio: str = "1:1"
    response_format: Literal["url", "base64"] = "url"
    n: int = Field(default=1, ge=1, le=9)
    prompt_optimizer: bool = True
    seed: int | None = None
    width: int | None = Field(default=None, ge=512, le=2048)
    height: int | None = Field(default=None, ge=512, le=2048)
    aigc_watermark: bool = False
    style: dict[str, Any] | None = None
    subject_reference: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def validate_image_options(self) -> "ImageGenerationRequest":
        if self.aspect_ratio not in IMAGE_ASPECT_RATIOS:
            raise ValueError(f"aspect_ratio must be one of {sorted(IMAGE_ASPECT_RATIOS)}")
        if (self.width is None) != (self.height is None):
            raise ValueError("width and height must be provided together")
        if self.width is not None and (self.width % 8 != 0 or self.height % 8 != 0):
            raise ValueError("width and height must be multiples of 8")
        return self

    def minimax_extra(self) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        for key in ("seed", "width", "height", "style", "subject_reference"):
            value = getattr(self, key)
            if value is not None:
                extra[key] = value
        if self.aigc_watermark:
            extra["aigc_watermark"] = True
        return extra


class GeneratedImage(BaseModel):
    index: int
    url: str | None = None
    base64: str | None = None
    mime_type: str = "image/png"


class ImageGenerationResponse(BaseModel):
    id: str = ""
    provider: str = "minimax"
    model: str
    prompt: str
    aspect_ratio: str
    response_format: str
    images: list[GeneratedImage]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_minimax(
        cls,
        raw: dict[str, Any],
        request: ImageGenerationRequest,
        *,
        model: str,
    ) -> "ImageGenerationResponse":
        return cls(
            id=str(raw.get("id") or ""),
            model=model,
            prompt=request.prompt,
            aspect_ratio=request.aspect_ratio,
            response_format=request.response_format,
            images=_extract_minimax_images(raw),
            metadata=raw.get("metadata") or {},
        )


def _extract_minimax_images(raw: dict[str, Any]) -> list[GeneratedImage]:
    data = raw.get("data") or {}
    images: list[GeneratedImage] = []

    for url in _as_list(data.get("image_urls")):
        if url:
            images.append(GeneratedImage(index=len(images), url=str(url)))

    for value in _as_list(
        data.get("image_base64")
        or data.get("image_base64s")
        or data.get("image_base64_list")
        or data.get("base64")
        or data.get("b64_json")
    ):
        if value:
            images.append(
                GeneratedImage(
                    index=len(images),
                    base64=_strip_data_url_prefix(str(value)),
                )
            )

    for item in _as_list(data.get("images")):
        if isinstance(item, str):
            field = "url" if item.startswith(("http://", "https://")) else "base64"
            value = item if field == "url" else _strip_data_url_prefix(item)
            images.append(GeneratedImage(index=len(images), **{field: value}))
            continue
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("image_url")
        b64 = item.get("base64") or item.get("image_base64") or item.get("b64_json")
        if url or b64:
            images.append(
                GeneratedImage(
                    index=len(images),
                    url=str(url) if url else None,
                    base64=_strip_data_url_prefix(str(b64)) if b64 else None,
                    mime_type=str(item.get("mime_type") or "image/png"),
                )
            )

    return images


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _strip_data_url_prefix(value: str) -> str:
    if value.startswith("data:") and "," in value:
        return value.split(",", 1)[1]
    return value
