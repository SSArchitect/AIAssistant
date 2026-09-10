from __future__ import annotations

import re
from typing import Any

# Provider-neutral rules adapted from https://developers.openai.com/api/docs/guides/image-prompting
# after the 2026-09-10 Spark prompt comparison. Keep model-specific API options out.
IMAGE_PROMPT_GUIDANCE = (
    "\n- 明确用户要求的图片用途，按场景、主体、可见细节、构图与约束组织提示词；"
    "标签只为清晰可读，不依赖特殊语法。"
    "\n- 保留主体数量、相对位置、比例、留白区域和禁止出现的内容；"
    "不擅自增加人物、道具、品牌、文字或故事。用户已经明确的细节只整理，不随意扩写。"
    "\n- 保留用户指定的视觉媒介；仅在写实需求下明确自然摄影纹理，"
    "不要把插画等其他风格强制改成照片。"
    "\n- 尺寸、seed 等 API 参数与视觉内容分开，遵循当前 Provider 的参数规则；"
    "只补充有用信息，消除冲突和重复，不堆砌画质口号。"
)

PROFESSIONAL_IMAGE_PROMPT_GUIDANCE = (
    "\n- 将氛围落实为可见的光线方向、明暗、材质与色彩；"
    "镜头参数只作为外观提示，避免互相矛盾的景深与清晰度要求。"
    "\n- 主体有动作时，说明视线方向、身体取景、相对尺度和接触位置，"
    "保留用户给定的动作与物体数量、容量等细节；遵循物种自然肢体结构，"
    "不把动物前爪描述成人手抓握，不额外设计复杂姿势。"
)

SHORT_IMAGE_TEXT_GUIDANCE = (
    "\n- 用户要求的简短文字用引号原样保留，说明位置、排版和出现次数，不添加其他文案；"
    "用户要求无文字时，明确禁止文字、标志或水印。"
)

TEXT_HEAVY_MARKERS = (
    "信息图",
    "对比图",
    "长图",
    "分享图",
    "一图看懂",
    "图表",
    "表格",
    "卡片",
    "五维",
    "评分",
    "星级",
    "时长",
    "推荐人群",
    "道路类型",
    "图内文字",
    "必须呈现",
    "必须包含",
    "免责",
    "小红书",
    "朋友圈",
    "infographic",
    "comparison chart",
    "share card",
    "table",
    "text labels",
    "exact text",
    "caption",
)

TEXT_RENDERING_GUARD = (
    "文字渲染保护：不要在生成图片中渲染详细中文、精确表格、段落、星级评分行、"
    "小字号脚注或精确道路/时间标签。只使用图标、编号徽章、色条和抽象占位文本带；"
    "精确文案交给独立 UI/SVG 排版覆盖。"
)

TEXT_RENDERING_NOTE = (
    "已识别为文字密集型分享图：生图只做版式/图标，精确中文建议由前端或 SVG 真实排版。"
)


def is_text_heavy_visual_intent(
    *,
    message: str = "",
    research_brief: str = "",
    context_blocks: list[str] | None = None,
    mode_prompts: list[str] | None = None,
) -> bool:
    """Detect image requests that need real typography instead of raw image text."""
    text = "\n".join(
        [
            message or "",
            research_brief or "",
            "\n".join(context_blocks or []),
            "\n".join(mode_prompts or []),
        ]
    ).lower()
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return False

    marker_hits = sum(1 for marker in TEXT_HEAVY_MARKERS if marker in normalized)
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", normalized))
    digit_count = len(re.findall(r"\d", normalized))
    structured_rows = len(re.findall(r"(^|\n)\s*(?:[-*]|\d+[.)、]|[|])", text))
    explicitly_exact = any(
        phrase in normalized
        for phrase in (
            "图内文字",
            "必须呈现",
            "必须包含",
            "exact text",
            "text labels",
            "small text",
        )
    )

    if explicitly_exact and marker_hits >= 1:
        return True
    if has_cjk and marker_hits >= 2 and (digit_count >= 3 or structured_rows >= 3):
        return True
    if has_cjk and marker_hits >= 3 and len(normalized) >= 220:
        return True
    return False


def apply_text_rendering_guard(review: dict[str, Any]) -> dict[str, Any]:
    """Add image-prompt constraints for dense text layouts while preserving review shape."""
    if not review.get("should_generate") or not review.get("final_prompt"):
        return review

    guarded = dict(review)
    final_prompt = str(guarded.get("final_prompt") or "").strip()
    if TEXT_RENDERING_GUARD.lower() not in final_prompt.lower():
        max_prompt_len = 1500
        available = max_prompt_len - len(TEXT_RENDERING_GUARD) - 1
        if available > 0 and len(final_prompt) > available:
            final_prompt = final_prompt[:available].rstrip()
        final_prompt = f"{final_prompt} {TEXT_RENDERING_GUARD}".strip()
    guarded["final_prompt"] = final_prompt[:1500].rstrip()

    review_notes = list(guarded.get("review_notes") or [])
    if TEXT_RENDERING_NOTE not in review_notes:
        review_notes.insert(0, TEXT_RENDERING_NOTE)
    guarded["review_notes"] = review_notes[:4]
    return guarded
