"""Typed media-node boundary for the creation workspace (no chat/LLM routing)."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.aigc.image_inputs import decode_image_data_url, load_image_url
from agent.aigc.image_service import generate_image
from agent.aigc.creation_image_context import ImageReferenceContext, style_only_prompt
from agent.aigc.video_service import generate_video
from agent.aigc.video_prompting import VideoStoryboard, compile_storyboard
from agent.schemas.aigc import ImageGenerationRequest, VideoGenerationRequest

router = APIRouter()
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
OUTPUT_DIR = Path(__file__).resolve().parents[2] / 'web/static/generated/aigc'


class CreationNodeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['image', 'video']
    prompt: str = Field(min_length=1, max_length=4000)
    aspect_ratio: Literal['1:1', '16:9', '9:16'] = '1:1'
    duration_seconds: int = Field(default=5, ge=1, le=15)
    character_style: Literal['', 'anime', 'chibi'] = ''
    image_references: list[ImageReferenceContext] = Field(default_factory=list, max_length=1)
    input_images: list[str] = Field(default_factory=list, max_length=9)
    idempotency_key: str = Field(min_length=1, max_length=128)
    video_mode: Literal['', 'text_to_video', 'image_to_video', 'reference_to_video'] = ''
    storyboard: VideoStoryboard | None = None

    @model_validator(mode='after')
    def validate_inputs(self):
        if not self.prompt.strip():
            raise ValueError('请输入提示词')
        if self.kind == 'image' and len(self.input_images) > 1:
            raise ValueError('生图节点最多引用一张图片')
        if self.character_style and (self.kind != 'image' or not self.input_images):
            raise ValueError('人物风格模板需要一张参考图片')
        if self.image_references and (self.kind != 'image' or len(self.image_references) != len(self.input_images)):
            raise ValueError('图片参考职责必须与图片输入逐一对应')
        for value in self.input_images:
            decode_image_data_url(value)
        if self.kind == 'image' and (self.video_mode or self.storyboard):
            raise ValueError('图片节点不能携带视频方案')
        if self.video_mode == 'image_to_video' and len(self.input_images) != 1:
            raise ValueError('首帧模式需要一张图片')
        if self.video_mode == 'text_to_video' and self.input_images:
            raise ValueError('文生视频不能包含参考图')
        if self.video_mode == 'reference_to_video' and not self.input_images:
            raise ValueError('参考模式需要图片')
        return self


async def execute_node(request: CreationNodeRequest):
    if request.kind == 'image':
        options = dict(provider='spark', prompt=request.prompt, aspect_ratio=request.aspect_ratio,
                       idempotency_key=request.idempotency_key)
        reference = request.image_references[0] if request.image_references else None
        if reference and reference.role == 'style':
            # Style guides never become img2img source pixels or identity templates.
            options['prompt'] = await style_only_prompt(request.prompt, request.input_images[0], reference, request.idempotency_key)
            options['mode'] = 'text_to_image'
        else:
            if request.input_images:
                options['image_data_url'] = request.input_images[0]
            if request.character_style:
                options.update(mode='character_stylization', character_style=request.character_style)
            if reference and reference.note:
                addition = '\nReference responsibility (' + reference.role + '): ' + reference.note
                if len(options['prompt']) + len(addition) <= 4000:
                    options['prompt'] += addition
        result = await generate_image(ImageGenerationRequest(**options))
        if len(result.images) != 1:
            raise ValueError('生图服务未返回一张图片')
        item = result.images[0]
        data = f'data:{item.mime_type};base64,{item.base64}' if item.base64 else await load_image_url(item.url or '')
        content, mime = decode_image_data_url(data)
    else:
        width, height = {'1:1': (704, 704), '16:9': (864, 480), '9:16': (480, 864)}[request.aspect_ratio]
        options = dict(prompt=request.prompt, width=width, height=height,
                       duration_seconds=float(request.duration_seconds), idempotency_key=request.idempotency_key)
        if request.video_mode == 'reference_to_video':
            options['reference_image_data_urls'] = request.input_images
        elif len(request.input_images) == 1:
            options['first_frame_data_url'] = request.input_images[0]
        elif request.input_images:
            options['reference_image_data_urls'] = request.input_images
        video_request = VideoGenerationRequest(**options)
        if request.storyboard:
            compiled = compile_storyboard(request.storyboard, video_request)
            if compiled != request.prompt:
                raise ValueError('分镜与已确认提示词不一致，请重新规划和审阅')
        result = await generate_video(video_request)
        if len(result.videos) != 1:
            raise ValueError('生视频服务未返回一个视频')
        url = result.videos[0].url
        prefix = '/static/generated/aigc/'
        target = (OUTPUT_DIR / url.removeprefix(prefix)).resolve()
        if not url.startswith(prefix) or target.parent != OUTPUT_DIR.resolve() or target.suffix != '.mp4':
            raise ValueError('无效的视频产物路径')
        with target.open('rb') as source:
            content = source.read(MAX_OUTPUT_BYTES + 1)
        if not content or len(content) > MAX_OUTPUT_BYTES:
            raise ValueError('视频资产必须小于 64 MiB')
        mime = 'video/mp4'
    return {'content': base64.b64encode(content).decode('ascii'), 'mime_type': mime,
            'provider_task_id': result.id}


@router.post('/agent/creation/node')
async def creation_node(request: CreationNodeRequest):
    try:
        return await execute_node(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Provider exceptions may contain credentials or internal URLs.
        raise HTTPException(status_code=502, detail='媒体生成失败，请检查生成服务配置后重试') from exc
