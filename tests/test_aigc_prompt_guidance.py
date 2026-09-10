"""Prompt contracts at the image review boundary; no live model calls."""
import pytest

from agent.schemas.chat import ChatRequest
from agent.schemas.memory import MemoryContext, RoleProfile


def review_messages(engine, *, professional=False, provider="spark", message=None):
    return engine._build_aigc_review_messages(
        request=ChatRequest(
            conversation_id="image-guidance-test",
            agent_id="image_generation_v1",
            message=message or "橘猫扶着半杯水，主体在右侧，左侧三分之一留白，无文字。",
            image_options={"provider": provider, "width": 1536, "height": 1024, "seed": 42},
        ),
        role_context=MemoryContext(role=RoleProfile(id="default", name="默认助手")),
        history=[],
        professional=professional,
    )


@pytest.mark.parametrize("provider", ["spark", "minimax"])
@pytest.mark.parametrize("professional", [False, True])
def test_image_review_preserves_layout_and_intent(engine, provider, professional):
    original = "扁平插画：橘猫在右侧，左侧三分之一留白，无文字，不加道具。"
    messages = review_messages(engine, provider=provider, professional=professional, message=original)
    system = messages[0].content

    assert original in messages[1].content
    assert "主体数量、相对位置、比例、留白区域" in system
    assert "不擅自增加人物、道具、品牌、文字或故事" in system
    assert "不要把插画等其他风格强制改成照片" in system
    assert "尺寸、seed 等 API 参数与视觉内容分开" in system
    assert '"negative_prompt"' in system
    assert "长度不超过 1500 字符" in system
    assert ("单边 256–4096" in system) == (provider == "spark")


def test_professional_review_adds_visible_detail_without_expanding_light_mode(engine):
    light = review_messages(engine)[0].content
    professional = review_messages(engine, professional=True)[0].content

    assert "视线方向、身体取景、相对尺度和接触位置" in professional
    assert "不把动物前爪描述成人手抓握" in professional
    assert "镜头参数只作为外观提示" in professional
    assert "视线方向、身体取景、相对尺度和接触位置" not in light
    assert "已启用轻量审查" in light


@pytest.mark.parametrize("professional", [False, True])
def test_dense_text_policy_takes_precedence_over_exact_text_guidance(engine, professional):
    system = review_messages(
        engine,
        professional=professional,
        message="中文信息图，必须呈现精确表格、评分和小字号免责声明。",
    )[0].content

    assert "当前图片模型不擅长精确中文、密集表格和小字号标签" in system
    assert "精确中文文案和事实行不要进入生成像素" in system
    assert "用户要求的简短文字用引号原样保留" not in system


def test_short_copy_guidance_does_not_add_unrequested_text(engine):
    system = review_messages(engine, message='极简海报，标题为“晨光”。')[0].content

    assert "用户要求的简短文字用引号原样保留" in system
    assert "位置、排版和出现次数" in system
    assert "用户要求无文字时，明确禁止文字、标志或水印" in system
