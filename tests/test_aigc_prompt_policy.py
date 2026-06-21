from agent.aigc.prompt_policy import (
    TEXT_RENDERING_GUARD,
    TEXT_RENDERING_NOTE,
    apply_text_rendering_guard,
    is_text_heavy_visual_intent,
)


def test_text_heavy_visual_policy_detects_dense_chinese_share_card():
    assert is_text_heavy_visual_intent(
        message="帮我把这几个方案生成一个图片吧，方便分享",
        research_brief=(
            "视觉简报：中文分享图，必须呈现评分、时长、道路类型、推荐人群和免责语。\n"
            "1. 巽寮湾 ⭐⭐⭐⭐⭐｜1.5h｜全高速+沿海大道｜全家、情侣\n"
            "2. 西湖市区 ⭐⭐⭐⭐｜1h｜高速+市区｜老人、不想开车\n"
            "3. 双月湾 ⭐⭐⭐⭐｜2h｜高速+县道｜喜欢小众"
        ),
    )


def test_text_rendering_guard_adds_reusable_image_agent_constraints():
    review = {
        "should_generate": True,
        "final_prompt": "A Chinese infographic with exact labels and star ratings.",
        "review_notes": ["保留核心对比信息"],
    }

    guarded = apply_text_rendering_guard(review)

    assert TEXT_RENDERING_GUARD in guarded["final_prompt"]
    assert guarded["review_notes"][0] == TEXT_RENDERING_NOTE
    assert guarded["review_notes"][1] == "保留核心对比信息"
