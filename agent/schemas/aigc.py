from __future__ import annotations

from fractions import Fraction
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator


IMAGE_ASPECT_RATIOS = {"1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"}
VIDEO_MAX_PIXELS = 1032192
VIDEO_MAX_PIXEL_FRAMES = 373653504
VIDEO_MAX_FRAMES = 3592
VIDEO_NATIVE_FPS = 24
VIDEO_MAX_SEED = 18446744073709551615


class VideoGenerationRequest(BaseModel):
    """Provider v0.5 contract; retain the requested time input for idempotent replay."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=1, max_length=4000)
    width: int = Field(default=864, strict=True, ge=32, le=4096, multiple_of=32)
    height: int = Field(default=480, strict=True, ge=32, le=4096, multiple_of=32)
    num_frames: int | None = Field(default=None, strict=True, ge=5, le=VIDEO_MAX_FRAMES)
    duration_seconds: float | None = Field(default=None, strict=True, gt=0,
        le=VIDEO_MAX_FRAMES / VIDEO_NATIVE_FPS, allow_inf_nan=False)
    fps: float = Field(default=24, strict=True, ge=1, le=120, allow_inf_nan=False)
    seed: Annotated[StrictInt, Field(ge=-1, le=VIDEO_MAX_SEED)] | Annotated[
        StrictStr, Field(pattern=r"^[0-9]{1,20}$")
    ] | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def default_frames(cls, value):
        if isinstance(value, dict) and "num_frames" not in value and "duration_seconds" not in value:
            return {**value, "num_frames": 124}
        return value

    @field_validator("seed")
    @classmethod
    def normalize_seed(cls, value):
        if value is None or value == -1:
            return None
        number = int(value)
        if number > VIDEO_MAX_SEED:
            raise ValueError("seed exceeds unsigned 64-bit range")
        # Preserve all 64 bits through tool arguments, Trace and browser JSON round trips.
        return str(number)

    @field_validator("fps")
    @classmethod
    def validate_fps_precision(cls, value):
        if (Fraction(str(value)) * 1000).denominator != 1:
            raise ValueError("fps accepts at most 3 decimal places")
        return value

    @model_validator(mode="after")
    def validate_video_options(self) -> "VideoGenerationRequest":
        if not self.prompt.strip():
            raise ValueError("prompt cannot be blank")
        if (self.num_frames is None) == (self.duration_seconds is None):
            raise ValueError("provide exactly one of num_frames and duration_seconds, or omit both")
        if self.width * self.height > VIDEO_MAX_PIXELS:
            raise ValueError(f"width * height must not exceed {VIDEO_MAX_PIXELS}")
        if self.width * self.height * self.resolved_frames() > VIDEO_MAX_PIXEL_FRAMES:
            raise ValueError(f"width * height * aligned native frames must not exceed {VIDEO_MAX_PIXEL_FRAMES}")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("idempotency_key cannot be blank")
        return self

    def resolved_frames(self) -> int:
        requested = self.num_frames if self.num_frames is not None else math.ceil(
            Fraction(str(self.duration_seconds)) * VIDEO_NATIVE_FPS)
        return 5 + 17 * max(0, math.ceil(Fraction(requested - 5, 17)))


class GeneratedVideo(BaseModel):
    index: int
    url: str
    mime_type: str = "video/mp4"


class VideoGenerationResponse(BaseModel):
    id: str
    provider: str = "spark"
    prompt: str
    videos: list[GeneratedVideo]
    seed_text: str | None = None
    video: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    provider: Literal["minimax", "spark"] | None = None
    negative_prompt: str = Field(default="", max_length=4000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    model: str | None = None
    aspect_ratio: str = "1:1"
    response_format: Literal["url", "base64"] = "url"
    n: int = Field(default=1, ge=1, le=9)
    prompt_optimizer: bool = True
    seed: int | None = Field(default=None, strict=True, ge=0, le=4294967295)
    width: int | None = Field(default=None, strict=True, ge=256, le=4096)
    height: int | None = Field(default=None, strict=True, ge=256, le=4096)
    aigc_watermark: bool = False
    style: dict[str, Any] | None = None
    subject_reference: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def validate_image_options(self) -> "ImageGenerationRequest":
        if not self.prompt.strip():
            raise ValueError("prompt cannot be blank")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("idempotency_key cannot be blank")
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
