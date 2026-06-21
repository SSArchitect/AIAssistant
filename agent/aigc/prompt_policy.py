from __future__ import annotations

import re
from typing import Any

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
