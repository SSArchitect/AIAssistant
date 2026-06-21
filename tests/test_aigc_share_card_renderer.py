from pathlib import Path

from agent.aigc.share_card_renderer import (
    build_share_card_summary,
    build_structured_share_card_brief,
    extract_share_card_rows,
    render_share_card_svg,
)


HUIZHOU_BRIEF = """
Context Reuse Brief: reuse the already researched conversation facts below.

Current image request:
我说，重新生成一下图片

Reusable facts and layout source:
# 深圳自驾惠州·方案舒适度深度对比

## 一句话结论
自驾最舒服 -> 巽寮湾

| 方案 | 单程时长 | 道路类型 | 停车难度 | 疲劳度 | 推荐人群 |
|---|---|---|---|---|---|
| **🏖️ 巽寮湾** | 1.5h | 全高速+沿海大道 | ⭐ 容易 | ⭐ 最低 | 全家、情侣 |
| 西湖市区 | 1h | 高速+市区 | ⭐⭐ 较易 | ⭐⭐ 偏低 | 老人、不想开车 |
| 双月湾 | 2h | 高速+县道 | ⭐⭐⭐ 中等 | ⭐⭐⭐ 中等 | 喜欢小众 |
| 罗浮山 | 1.5h | 高速+山路 | ⭐⭐ 较易 | ⭐⭐⭐ 偏高 | 登山爱好者 |
| 南昆山 | 2.5h | 高速+盘山路 | ⭐⭐⭐⭐ 较难 | ⭐⭐⭐⭐ 最高 | 自驾老手 |
"""


def test_share_card_renderer_extracts_rows_and_builds_structured_brief(tmp_path: Path):
    rows = extract_share_card_rows(HUIZHOU_BRIEF)

    assert len(rows) == 5
    assert rows[0].name == "巽寮湾"
    assert rows[0].duration == "1.5h"
    assert rows[0].road == "全高速+沿海大道"
    assert rows[-1].name == "南昆山"

    structured = build_structured_share_card_brief(HUIZHOU_BRIEF)
    assert "数据行：" in structured
    assert "巽寮湾 | 时长=1.5h" in structured
    assert "注意事项：精确中文事实必须由确定性的 UI/SVG 文字渲染" in structured

    summary = build_share_card_summary(HUIZHOU_BRIEF)
    assert summary[0].startswith("已整理为「深圳自驾惠州")
    assert "核心结论：首推 巽寮湾" in summary

    result = render_share_card_svg(HUIZHOU_BRIEF, run_id="unit_test", output_dir=tmp_path)
    assert result is not None
    assert result.row_count == 5
    svg = result.path.read_text(encoding="utf-8")
    assert "巽寮湾" in svg
    assert "南昆山" in svg
    assert "中文文字由结构化 SVG 渲染" in svg
