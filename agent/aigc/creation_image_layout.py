"""Place one small subject by editing a scene region, then restoring its boundary.

Layout is an execution recipe, never an approval criterion. Original references
and the full assembled image still go through ordinary independent review.
"""
from __future__ import annotations

import base64
from io import BytesIO
import math

from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, model_serializer
from typing import Literal

from agent.aigc.image_inputs import decode_image_data_url
from agent.aigc.creation_identity_context import isolated_identity_view

CANVASES = {'1:1': (1024, 1024), '16:9': (1024, 576), '9:16': (576, 1024)}
LAYOUT_GUIDANCE = '''分镜图中小主体反复被画成大特写时，可使用image_layout局部构图能力，而非继续堆叠整图提示词。当前支持一个主体：仅shot_reference、恰好一个environment与一个identity参考；不能同时用edit_source_asset_id、asset_id或人物风格模板。image_layout=[{center_x_percent,center_y_percent,subject_height_percent,subject_prompt}]。中心坐标为最终画幅百分比，subject_height_percent为主体连同坐骑/道具的总高度（3–25），四周要留够区域，不能出画。系统从已确认环境截取小区域，让生图模型在局部清晰描绘主体，再合回原位置；区域外像素保持不变。subject_prompt仅描述这个角色的身份、姿态、动作、服装、道具与光线，不复述全景、不写全画幅小比例；视线只写方向（如向上或前下方），不在局部描述中重述画外树冠、蝴蝶等环境目标，环境已在原图中；局部占比由工具编译。构图参数由你按冻结创作要求与实际场景判断，不交给用户填写；不能改变原内容、验收标准或将失败候选冒充已确认参考。空数组image_layout=[]恢复普通整图生成。该能力不保证视觉通过，新候选仍须整图审阅。若局部图反复带入底纸/矩形背景，可显式选择composite_mode=foreground_v1：先生成可分离底色的人物层，再加留白补全人物和道具，透明合入原场景，仅改变前景像素。此模式通常有两次生图调用，各阶段可断点恢复。subject_prompt只写主体身份/动作/服装/道具/光线，不写抠色、去背景、裁切、边距或柔化指令；底色和补全由工具处理。不得改变原冻结目标。旧模式省略composite_mode或设空字符串。'''


class ImagePlacement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    center_x_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    center_y_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    subject_height_percent: float = Field(ge=3, le=25, allow_inf_nan=False)
    subject_prompt: str = Field(min_length=1, max_length=1800, pattern=r'\S')
    composite_mode: Literal['', 'foreground_v1'] = ''

    @model_serializer(mode='wrap')
    def serialize_legacy(self, handler):
        result = handler(self)
        if not self.composite_mode:
            result.pop('composite_mode', None)
        return result


def region_box(placement, aspect_ratio):
    width, height = CANVASES[aspect_ratio]
    side = 2 * math.ceil(height * placement.subject_height_percent / 100 / .74 / 2)
    cx = math.floor(width * placement.center_x_percent / 100 + .5)
    cy = math.floor(height * placement.center_y_percent / 100 + .5)
    box = (cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2)
    if box[0] < 0 or box[1] < 0 or box[2] > width or box[3] > height:
        raise ValueError('局部构图区域超出画幅，请调整主体中心或比例')
    return box


def validate_layout(layout, aspect_ratio, kind, purpose, refs, style, bound):
    if not layout:
        return
    if (len(layout) != 1 or kind != 'image' or purpose != 'shot_reference' or style or bound
            or sorted(ref.role for ref in refs) != ['environment', 'identity']):
        raise ValueError('局部构图仅支持一个分镜主体、一个环境与一个身份参考，不混用编辑草稿、成品或人物模板')
    region_box(layout[0], aspect_ratio)


def read_image(data):
    content, _ = decode_image_data_url(data)
    with Image.open(BytesIO(content)) as image:
        return ImageOps.exif_transpose(image).convert('RGB')


def png_bytes(image):
    out = BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


async def prepare_region(request, *, resume=False):
    layout = request.image_layout[0]
    box = region_box(layout, request.aspect_ratio)
    sources = {ref.role: (index, data, ref) for index, (data, ref) in enumerate(zip(request.input_images, request.image_references), 1)}
    original = read_image(sources['environment'][1])
    width, height = CANVASES[request.aspect_ratio]
    # A different aspect cannot preserve composition: require a matching scene.
    if abs(original.width / original.height / (width / height) - 1) > .02:
        raise ValueError('局部构图需要与目标画幅一致的场景参考图')
    original = original.resize((width, height), Image.Resampling.LANCZOS)
    crop = original.crop(box).resize((512, 512), Image.Resampling.LANCZOS)
    index, identity, ref = sources['identity']
    if layout.composite_mode == 'foreground_v1':
        from agent.aigc.creation_foreground import prepare_foreground
        return await prepare_foreground(request, original, crop, identity, ref, index, resume=resume)
    if not resume:
        identity = await isolated_identity_view(identity, ref, layout.subject_prompt, request.idempotency_key + ':' + str(index))
    # Resume only looks up an already accepted task. It never resubmits or invokes
    # reference extraction; final composition still uses the frozen original scene.
    prompt = ('Picture 1 is a close-up EMPTY REGION of an existing scene, not a whole landscape. '
        'Preserve its background, lighting and visible environment edges. Add ONE subject using only '
        'the identity, proportions, clothing and owned props from Picture 2. Use its pose only where it '
        'matches the target action and explicit reference responsibility below. '
        'Do not recreate a whole landscape inside this crop. '
        'Picture 2 responsibility (never its background or sheet layout): ' + ref.note + '\n'
        'Target subject and action: ' + layout.subject_prompt + '\n'
        'Gaze targets are outside this local crop. Convey the requested gaze DIRECTION only; '
        'do not draw extra scenery, creatures or objects to illustrate what the subject is looking at. '
        'The complete subject including its ridden/held prop occupies approximately 74 percent of this '
        'cropped image height, centered in the region. Keep the full subject and props inside the crop. '
        'Copy no studio background, sheet layout or text from Picture 2. Match the rendering and light '
        'of Picture 1. One continuous square image, no extra figures, no zoom-out to a whole landscape.')
    return (original, box), dict(prompt=prompt, mode='reference_to_image', aspect_ratio='1:1', width=512, height=512,
        reference_image_data_urls=['data:image/png;base64,' + base64.b64encode(png_bytes(crop)).decode(), identity])


def compose_region(region, generated):
    """Poisson boundary blend. Bounded CPU work; untouched pixels stay identical."""
    from agent.aigc.creation_foreground import ForegroundRegion, composite_foreground
    if isinstance(region, ForegroundRegion):
        return composite_foreground(region, generated)
    import numpy as np
    original, box = region
    size = (box[2] - box[0], box[3] - box[1])
    with Image.open(BytesIO(generated)) as image:
        if image.size != (512, 512):
            raise ValueError('局部生成返回了非512方形图片，不能按原构图合成')
        patch = np.asarray(image.convert('RGB').resize(size, Image.Resampling.LANCZOS), dtype=np.float64)
    target = np.asarray(original.crop(box), dtype=np.float64)
    boundary = target - patch
    correction = np.zeros_like(boundary)
    correction[0] = boundary[0]
    correction[-1] = boundary[-1]
    correction[:, 0] = boundary[:, 0]
    correction[:, -1] = boundary[:, -1]
    # Solve the discrete Dirichlet Laplacian with a DST-I (via FFT). Unlike an
    # iterative solver this has fixed O(n log n) work and no convergence stalls.
    rhs = np.zeros_like(correction[1:-1, 1:-1])
    rhs[0] += correction[0, 1:-1]
    rhs[-1] += correction[-1, 1:-1]
    rhs[:, 0] += correction[1:-1, 0]
    rhs[:, -1] += correction[1:-1, -1]

    def sine_transform(array, axis):
        n = array.shape[axis]
        shape = list(array.shape)
        shape[axis] = 2 * (n + 1)
        extended = np.zeros(shape)
        first = [slice(None)] * array.ndim
        second = list(first)
        first[axis] = slice(1, n + 1)
        second[axis] = slice(n + 2, None)
        extended[tuple(first)] = array
        extended[tuple(second)] = -np.flip(array, axis=axis)
        return -np.fft.fft(extended, axis=axis).imag[tuple(first)]

    rows, cols = rhs.shape[:2]
    eigenvalues = (4 - 2 * np.cos(np.pi * np.arange(1, rows + 1) / (rows + 1))[:, None]
        - 2 * np.cos(np.pi * np.arange(1, cols + 1) / (cols + 1))[None, :])
    coefficients = sine_transform(sine_transform(rhs, 0), 1) / eigenvalues[:, :, None]
    correction[1:-1, 1:-1] = sine_transform(sine_transform(coefficients, 0), 1) / (4 * (rows + 1) * (cols + 1))
    blended = np.clip(np.rint(patch + correction), 0, 255).astype('uint8')
    final = original.copy()
    final.paste(Image.fromarray(blended), box[:2])
    return png_bytes(final)
