from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "web" / "static" / "generated" / "aigc"


@dataclass(frozen=True)
class ShareCardRow:
    name: str
    duration: str = ""
    road: str = ""
    parking: str = ""
    fatigue: str = ""
    audience: str = ""
    rating: str = ""
    tag: str = ""


@dataclass(frozen=True)
class ShareCardRenderResult:
    url: str
    path: Path
    title: str
    conclusion: str
    row_count: int


def extract_share_card_rows(brief: str, *, max_rows: int = 6) -> list[ShareCardRow]:
    """Extract comparison rows from Markdown tables or structured row bullets."""
    text = brief or ""
    rows = _extract_table_rows(text)
    if len(rows) < 2:
        rows = _extract_pipe_bullet_rows(text)
    if len(rows) < 2:
        rows = _extract_compact_bullet_rows(text)
    return rows[:max_rows]


def build_structured_share_card_brief(brief: str) -> str:
    """Normalize a reused/researched brief into the format expected by the image agent planner."""
    rows = extract_share_card_rows(brief, max_rows=8)
    if len(rows) < 2:
        return ""

    title = extract_share_card_title(brief)
    conclusion = extract_share_card_conclusion(brief, rows)
    lines = [
        f"目标：为「{title}」生成一张事实准确的分享卡。",
        f"必须包含：{conclusion}；展示 {len(rows)} 个方案，并尽量保留行车时长、道路复杂度、停车、疲劳度和推荐人群。",
        "数据行：",
    ]
    for row in rows:
        details = [
            row.name,
            f"时长={row.duration or '未注明'}",
            f"道路={row.road or '未注明'}",
            f"停车={row.parking or '未注明'}",
            f"疲劳={row.fatigue or '未注明'}",
            f"人群={row.audience or '未注明'}",
        ]
        if row.rating:
            details.append(f"评分={row.rating}")
        if row.tag:
            details.append(f"标签={row.tag}")
        lines.append("- " + " | ".join(details))
    lines.extend(
        [
            "版式：竖版分享卡，简洁标题，高亮推荐方案，堆叠式对比行。",
            "视觉风格：干净的旅行 App 质感，中文排版清晰，地图/旅行元素克制点缀。",
            "注意事项：精确中文事实必须由确定性的 UI/SVG 文字渲染，不交给位图生图模型臆造。",
        ]
    )
    return "\n".join(lines)


def build_share_card_summary(brief: str, *, max_lines: int = 4) -> list[str]:
    rows = extract_share_card_rows(brief, max_rows=8)
    if len(rows) < 2:
        return []

    title = extract_share_card_title(brief)
    conclusion = extract_share_card_conclusion(brief, rows)
    lines = [
        f"已整理为「{title}」分享图，图片内包含真实标题、结论和对比数据。",
        f"核心结论：{conclusion}",
        f"共呈现 {len(rows)} 个方案，覆盖时长、道路、停车、疲劳度和推荐人群等信息。",
    ]
    first = rows[0]
    if first.name:
        detail = "、".join(
            part
            for part in [first.duration, first.road, first.parking, first.fatigue, first.audience]
            if part
        )
        if detail:
            lines.append(f"首项方案：{first.name}（{detail}）。")
    return lines[:max_lines]


def render_share_card_svg(
    brief: str,
    *,
    run_id: str,
    output_dir: Path | None = None,
) -> ShareCardRenderResult | None:
    rows = extract_share_card_rows(brief, max_rows=5)
    if len(rows) < 2:
        return None

    title = extract_share_card_title(brief)
    conclusion = extract_share_card_conclusion(brief, rows)
    safe_run_id = re.sub(r"[^A-Za-z0-9_-]+", "_", run_id or "aigc").strip("_") or "aigc"
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_run_id}_share_card.svg"
    path = output_dir / filename
    svg = _build_svg(title=title, conclusion=conclusion, rows=rows)
    path.write_text(svg, encoding="utf-8")

    if output_dir.resolve().is_relative_to((PROJECT_ROOT / "web" / "static").resolve()):
        rel = output_dir.resolve().relative_to((PROJECT_ROOT / "web" / "static").resolve())
        url = "/static/" + "/".join([*rel.parts, filename])
    else:
        url = str(path)
    return ShareCardRenderResult(
        url=url,
        path=path,
        title=title,
        conclusion=conclusion,
        row_count=len(rows),
    )


def extract_share_card_title(brief: str) -> str:
    text = brief or ""
    for raw_line in text.splitlines():
        line = _clean_cell(raw_line).strip("# ")
        if not line:
            continue
        if any(marker in line for marker in ("舒适度", "对比", "方案")) and not line.lower().startswith(
            ("context reuse brief", "goal:", "must include:", "目标：", "必须包含：")
        ):
            return _squeeze_title(line, fallback="方案舒适度对比")
    if "惠州" in text and "自驾" in text:
        return "深圳自驾惠州舒适度对比"
    return "方案舒适度对比"


def extract_share_card_conclusion(brief: str, rows: list[ShareCardRow] | None = None) -> str:
    text = brief or ""
    patterns = [
        r"(?:自驾最舒服|最舒服|首推|推荐)\s*(?:->|→|：|:)?\s*([^\n。；;]+)",
        r"一句话结论\s*(?:：|:)?\s*([^\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = _clean_cell(match.group(1)).strip("。；; ")
            if value.startswith("方案") or any(marker in value for marker in ("注意事项", "覆盖层", "精确文字")):
                continue
            if value:
                if "首推" in value or "推荐" in value:
                    return value[:40]
                return f"首推 {value[:32]}"
    if rows:
        return f"首推 {rows[0].name}"
    return "保留原有结论"


def _extract_table_rows(text: str) -> list[ShareCardRow]:
    rows: list[ShareCardRow] = []
    header: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or line.count("|") < 3:
            continue
        cells = [_clean_cell(cell) for cell in line.strip().strip("|").split("|")]
        if not cells or _is_separator_row(cells):
            continue
        if _is_header_row(cells):
            header = cells
            continue
        row = _row_from_cells(cells, header=header)
        if row:
            rows.append(row)
    return rows


def _extract_pipe_bullet_rows(text: str) -> list[ShareCardRow]:
    rows: list[ShareCardRow] = []
    in_data_rows = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if lowered.startswith("data rows") or line.startswith("数据行"):
            in_data_rows = True
            continue
        if in_data_rows and (
            re.match(r"^[A-Za-z ]+:", line)
            or re.match(r"^(目标|必须包含|版式|视觉风格|注意事项|来源说明|缺口)\s*[：:]", line)
        ):
            in_data_rows = False
        if "|" not in line and "｜" not in line:
            continue
        normalized = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", line).replace("｜", "|")
        cells = [_clean_cell(cell) for cell in normalized.split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) < 3 or _is_header_row(cells) or _is_separator_row(cells):
            continue
        row = _row_from_cells(cells, header=[])
        if row:
            rows.append(row)
    return rows


def _extract_compact_bullet_rows(text: str) -> list[ShareCardRow]:
    rows: list[ShareCardRow] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not re.match(r"^(?:[-*]|\d+[.)、])\s*", line):
            continue
        normalized = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", line).replace("｜", "|")
        if "|" not in normalized:
            continue
        cells = [_clean_cell(cell) for cell in normalized.split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) < 3:
            continue
        row = _row_from_cells(cells, header=[])
        if row:
            rows.append(row)
    return rows


def _row_from_cells(cells: list[str], *, header: list[str]) -> ShareCardRow | None:
    if not cells:
        return None
    name = _strip_key_prefix(cells[0])
    rating = _extract_stars(name) or _extract_rating_from_cells(cells)
    name = _clean_name(name)
    if not name or len(name) > 30:
        return None

    if header:
        get = lambda *keys: _first_cell_by_header(cells, header, keys)
        duration = get("时长", "时间", "duration")
        road = get("道路", "路况", "road")
        parking = get("停车", "parking")
        fatigue = get("疲劳", "累", "fatigue")
        audience = get("人群", "适合", "推荐", "audience")
        return ShareCardRow(
            name=name,
            duration=_strip_key_prefix(duration),
            road=_strip_key_prefix(road),
            parking=_strip_key_prefix(parking),
            fatigue=_strip_key_prefix(fatigue),
            audience=_strip_key_prefix(audience),
            rating=rating,
        )

    values = [_strip_key_prefix(cell) for cell in cells[1:]]
    duration = _first_matching(values, (r"\d+(?:\.\d+)?\s*h", r"小时", r"分钟"))
    remaining = [value for value in values if value != duration]
    road = _first_matching(remaining, (r"高速", r"县道", r"山路", r"大道", r"市区", r"盘山", r"road"))
    remaining = [value for value in remaining if value != road]
    parking = _first_matching(remaining, (r"停车", r"容易", r"较易", r"中等", r"较难", r"parking"))
    remaining = [value for value in remaining if value != parking]
    fatigue = _first_matching(remaining, (r"疲劳", r"最低", r"偏低", r"中等", r"偏高", r"最高", r"fatigue"))
    remaining = [value for value in remaining if value != fatigue]
    audience = _first_matching(remaining, (r"全家", r"情侣", r"老人", r"喜欢", r"爱好", r"自驾", r"人群", r"audience"))
    tag = ""
    if not audience and remaining:
        audience = remaining[0]
        remaining = remaining[1:]
    if remaining:
        tag = remaining[0]
    return ShareCardRow(
        name=name,
        duration=duration,
        road=road,
        parking=parking,
        fatigue=fatigue,
        audience=audience,
        rating=rating,
        tag=tag,
    )


def _build_svg(*, title: str, conclusion: str, rows: list[ShareCardRow]) -> str:
    width = 900
    height = 1200
    card_x = 54
    card_w = 792
    y = 248
    card_h = 142
    gap = 18
    accents = ["#E85D4F", "#1F9E89", "#2F6FDB", "#F2B84B", "#6C63A6"]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="900" height="1200" fill="#F6F4EE"/>',
        '<rect x="0" y="0" width="900" height="214" fill="#17383F"/>',
        '<path d="M0 190 C160 228 304 180 460 210 C628 242 736 188 900 214 L900 0 L0 0 Z" fill="#22545D" opacity="0.65"/>',
        _text(title, 64, 80, size=40, weight=800, fill="#FFFFFF"),
        _text("自驾舒适度 · 一图看清", 64, 126, size=25, weight=500, fill="#D9ECE9"),
        '<rect x="64" y="150" width="420" height="42" rx="21" fill="#F2B84B"/>',
        _text(conclusion, 86, 179, size=24, weight=800, fill="#17383F"),
    ]

    for idx, row in enumerate(rows[:5], start=1):
        fill = "#FFFDF8" if idx == 1 else "#FFFFFF"
        stroke = accents[(idx - 1) % len(accents)] if idx == 1 else "#DDD7CC"
        accent = accents[(idx - 1) % len(accents)]
        parts.append(f'<rect x="{card_x}" y="{y}" width="{card_w}" height="{card_h}" rx="18" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        parts.append(f'<circle cx="{card_x + 42}" cy="{y + 44}" r="23" fill="{accent}"/>')
        parts.append(_text(str(idx), card_x + 42, y + 53, size=22, weight=800, fill="#FFFFFF", anchor="middle"))
        if idx == 1:
            parts.append(f'<rect x="{card_x + 618}" y="{y + 24}" width="128" height="34" rx="17" fill="#17383F"/>')
            parts.append(_text("推荐", card_x + 682, y + 48, size=20, weight=800, fill="#FFFFFF", anchor="middle"))
        if row.rating:
            parts.append(_text(row.rating[:5], card_x + 622, y + 92, size=22, weight=700, fill=accent))

        parts.append(_text(row.name, card_x + 86, y + 47, size=29, weight=800, fill="#172124"))
        line1 = " · ".join(part for part in [f"单程 {row.duration}" if row.duration else "", row.road] if part)
        line2 = " · ".join(
            part
            for part in [
                f"停车 {row.parking}" if row.parking else "",
                f"疲劳 {row.fatigue}" if row.fatigue else "",
            ]
            if part
        )
        line3 = f"适合 {row.audience}" if row.audience else ""
        parts.extend(_wrapped_text(line1 or "行程信息待补充", card_x + 86, y + 78, max_chars=29, size=20, fill="#526367"))
        parts.extend(_wrapped_text(line2 or "舒适度信息待补充", card_x + 86, y + 106, max_chars=30, size=20, fill="#526367"))
        if line3:
            parts.extend(_wrapped_text(line3, card_x + 86, y + 132, max_chars=30, size=19, fill="#7A4C27"))
        y += card_h + gap

    parts.extend(
        [
            '<line x1="64" y1="1115" x2="836" y2="1115" stroke="#D8D1C3" stroke-width="1"/>',
            _text("基于会话资料生成 · 中文文字由结构化 SVG 渲染，避免生图乱码", 64, 1153, size=20, weight=500, fill="#6B6257"),
            "</svg>",
        ]
    )
    return "\n".join(parts)


def _text(
    value: str,
    x: int,
    y: int,
    *,
    size: int,
    weight: int,
    fill: str,
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,PingFang SC,Microsoft YaHei,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{fill}">{html.escape(value)}</text>'
    )


def _wrapped_text(value: str, x: int, y: int, *, max_chars: int, size: int, fill: str) -> list[str]:
    chunks = _wrap_chars(value, max_chars=max_chars, max_lines=2)
    return [
        _text(chunk, x, y + index * (size + 5), size=size, weight=500, fill=fill)
        for index, chunk in enumerate(chunks)
    ]


def _wrap_chars(value: str, *, max_chars: int, max_lines: int) -> list[str]:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    chunks: list[str] = []
    current = ""
    for char in text:
        if len(current) >= max_chars:
            chunks.append(current)
            current = char
            if len(chunks) >= max_lines:
                break
        else:
            current += char
    if current and len(chunks) < max_lines:
        chunks.append(current)
    if len(chunks) == max_lines and len("".join(chunks)) < len(text):
        chunks[-1] = chunks[-1].rstrip("，,。 ") + "..."
    return chunks


def _clean_cell(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`#]", "", text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_key_prefix(value: str) -> str:
    text = _clean_cell(value)
    text = re.sub(
        r"^(?:duration|road|parking|fatigue|audience|rating|tag|时长|道路|停车|疲劳|人群|推荐|评分|标签)\s*[=:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _clean_name(value: str) -> str:
    text = _strip_key_prefix(value)
    text = re.sub(r"[⭐★☆]+", "", text)
    text = re.sub(r"^[^\w\u4e00-\u9fff]+", "", text)
    text = re.sub(r"\s+", "", text)
    return text.strip(" ：:-")


def _extract_stars(value: str) -> str:
    stars = re.findall(r"[⭐★]", value or "")
    if stars:
        return "★" * min(5, len(stars))
    match = re.search(r"(?:rating|评分)\s*[=:：]\s*([★⭐]{1,5})", value or "", flags=re.IGNORECASE)
    if match:
        return "★" * min(5, len(match.group(1)))
    return ""


def _extract_rating_from_cells(cells: list[str]) -> str:
    for cell in cells[1:]:
        lowered = cell.lower()
        if any(marker in lowered for marker in ("rating", "评分", "舒适度", "推荐度")):
            stars = _extract_stars(cell)
            if stars:
                return stars
    return ""


def _first_cell_by_header(cells: list[str], header: list[str], keys: tuple[str, ...]) -> str:
    for index, heading in enumerate(header):
        lowered = heading.lower()
        if any(key.lower() in lowered for key in keys) and index < len(cells):
            return cells[index]
    return ""


def _first_matching(values: list[str], patterns: tuple[str, ...]) -> str:
    for value in values:
        if any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns):
            return value
    return ""


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r"[:\-\s]+", cell or "") for cell in cells)


def _is_header_row(cells: list[str]) -> bool:
    first = (cells[0] if cells else "").lower()
    if any(marker in first for marker in ("方案", "目的地", "名称", "name")):
        return True
    joined = "|".join(cells).lower()
    if "=" in joined:
        return False
    header_hits = sum(
        1
        for marker in ("单程", "时长", "道路", "停车", "推荐人群", "duration", "road", "parking", "audience")
        if marker in joined
    )
    return header_hits >= 2


def _squeeze_title(value: str, *, fallback: str) -> str:
    text = re.sub(r"\s+", "", value)
    text = text.replace("·", " · ")
    if not text:
        return fallback
    return text[:24]
