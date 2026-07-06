from __future__ import annotations

import re
from typing import Any

DEFAULT_RECALL_MAX_QUERIES = 2

CJK_INTENT_TERMS = {
    "安装",
    "测评",
    "对比",
    "购买",
    "攻略",
    "价格",
    "教程",
    "评测",
    "入门",
    "使用",
    "推荐",
    "维修",
    "学习",
    "选购",
    "指南",
}
CJK_FORMAT_TERMS = {
    "报告",
    "榜单",
    "教材",
    "教程",
    "课程",
    "论文",
    "手册",
    "书籍",
    "文档",
    "资料",
    "指南",
}
CJK_LOW_SIGNAL_SEGMENTS = {
    "比较",
    "方法",
    "哪个好",
    "哪些",
    "如何",
    "什么",
    "最新",
    "资料",
    "资源",
    "最好",
}


def build_query_variants(
    query: str,
    *,
    max_queries: int = DEFAULT_RECALL_MAX_QUERIES,
) -> list[str]:
    return build_query_rewrite_plan(query, max_queries=max_queries)["queries"]


def build_query_rewrite_plan(
    query: str,
    *,
    max_queries: int = DEFAULT_RECALL_MAX_QUERIES,
) -> dict[str, Any]:
    max_queries = max(1, max_queries)
    original = _normalize_query(query)
    if not original:
        return {
            "node": "query_rewrite",
            "strategy": "empty",
            "original_query": "",
            "queries": [],
        }

    has_search_syntax = _has_search_syntax(original)
    syntax_rewrites = _syntax_preserving_rewrite_queries(original) if has_search_syntax else []
    anchor_rewrites = [] if has_search_syntax else _anchor_rewrite_queries(original)
    phrase_rewrites = [] if has_search_syntax else _latin_phrase_rewrite_queries(original)
    acronym_rewrites = [] if has_search_syntax else _latin_acronym_rewrite_queries(original)
    variants = [*syntax_rewrites, *anchor_rewrites, *phrase_rewrites, original, *acronym_rewrites]
    if not has_search_syntax:
        for candidate in [
            _keyword_query(original),
            _latin_focus_query(original),
        ]:
            normalized = _normalize_query(candidate)
            if not normalized or normalized in variants:
                continue
            variants.append(normalized)
            if len(variants) >= max_queries:
                break
    variants = _dedupe(variants)[:max_queries]
    strategy = "keyword_recall"
    if has_search_syntax:
        strategy = "syntax_preserving_rewrite"
    elif anchor_rewrites:
        strategy = "anchor_rewrite"
    elif phrase_rewrites:
        strategy = "phrase_rewrite"
    return {
        "node": "query_rewrite",
        "strategy": strategy,
        "original_query": original,
        "queries": variants,
    }


def _has_search_syntax(query: str) -> bool:
    return bool(
        re.search(
            r'(?:"[^"]+"|\b(?:AND|OR|NOT)\b|\b(?:site|intitle|inurl|filetype|ext|before|after):\S+)',
            query or "",
        )
    )


def _syntax_preserving_rewrite_queries(query: str) -> list[str]:
    candidates: list[str] = []
    quoted = _quote_latin_title_phrases(query)
    if quoted != query:
        candidates.append(quoted)
    return _dedupe(candidates)


def _latin_phrase_rewrite_queries(query: str) -> list[str]:
    candidates: list[str] = []
    quoted = _quote_latin_title_phrases(query)
    if quoted != query:
        candidates.append(quoted)
    return _dedupe(candidates)


def _latin_acronym_rewrite_queries(query: str) -> list[str]:
    candidates: list[str] = []
    for phrase, acronym in _latin_title_acronyms(query):
        replaced = _normalize_query(re.sub(re.escape(phrase), acronym, query, count=1))
        if replaced != query:
            candidates.append(replaced)
    return _dedupe(candidates)


def _quote_latin_title_phrases(query: str) -> str:
    result = query
    for phrase in _latin_title_number_phrases(query):
        if _phrase_is_quoted(result, phrase):
            continue
        result = re.sub(re.escape(phrase), f'"{phrase}"', result, count=1)
    return _normalize_query(result)


def _latin_title_acronyms(query: str) -> list[tuple[str, str]]:
    acronyms: list[tuple[str, str]] = []
    for phrase in _latin_title_number_phrases(query):
        parts = phrase.split()
        if len(parts) < 3 or not parts[-1].isdigit():
            continue
        initials = "".join(part[0] for part in parts[:-1] if part[0].isalpha())
        if len(initials) < 2:
            continue
        acronyms.append((phrase, f"{initials.upper()}{parts[-1]}"))
    return acronyms


def _latin_title_number_phrases(query: str) -> list[str]:
    pattern = re.compile(
        r"\b(?:[A-Z][A-Za-z0-9]+|[A-Z]{2,})"
        r"(?:\s+(?:[A-Z][A-Za-z0-9]+|[A-Z]{2,})){1,5}"
        r"\s+\d\b"
    )
    return _dedupe(match.group(0) for match in pattern.finditer(query or ""))


def _phrase_is_quoted(query: str, phrase: str) -> bool:
    return f'"{phrase}"' in query or f"'{phrase}'" in query


def _anchor_rewrite_queries(query: str) -> list[str]:
    candidates: list[str] = []
    cjk_segments = _raw_cjk_segments(query)
    anchors = _standalone_cjk_anchors(cjk_segments)
    subject_terms = _subject_terms_from_intent_segments(cjk_segments)
    format_terms = _format_terms(cjk_segments)
    intent_terms = _intent_terms(cjk_segments)

    if anchors and subject_terms and format_terms:
        candidates.append(
            " ".join(
                [
                    f"{anchors[0]}{subject_terms[0]}{format_terms[0]}",
                    *anchors[1:],
                ]
            )
        )
    if anchors and subject_terms and intent_terms and format_terms:
        candidates.append(
            " ".join(
                [
                    f"{subject_terms[0]}{intent_terms[0]}{format_terms[0]}",
                    *anchors,
                ]
            )
        )
    if anchors and (subject_terms or format_terms):
        candidates.append(" ".join(_dedupe([*anchors, *subject_terms, *format_terms])))
    return [candidate for candidate in _dedupe(candidates) if candidate != query]


def _raw_cjk_segments(query: str) -> list[str]:
    segments: list[str] = []
    for raw in re.split(r"[\s,，;；/、|｜:：()（）\[\]【】\"'“”]+", query or ""):
        segments.extend(re.findall(r"[\u4e00-\u9fff]+", raw))
    return [segment for segment in segments if segment]


def _standalone_cjk_anchors(segments: list[str]) -> list[str]:
    anchors: list[str] = []
    for segment in segments:
        if len(segment) < 2 or len(segment) > 6:
            continue
        if segment in CJK_INTENT_TERMS or segment in CJK_FORMAT_TERMS:
            continue
        if segment in CJK_LOW_SIGNAL_SEGMENTS:
            continue
        if len(segment) > 4 and (
            any(term in segment for term in CJK_INTENT_TERMS)
            or any(term in segment for term in CJK_FORMAT_TERMS)
        ):
            continue
        anchors.append(segment)
    return _dedupe(anchors)


def _subject_terms_from_intent_segments(segments: list[str]) -> list[str]:
    subjects: list[str] = []
    for segment in segments:
        for marker in sorted(CJK_INTENT_TERMS | CJK_FORMAT_TERMS, key=len, reverse=True):
            index = segment.find(marker)
            if index < 2:
                continue
            prefix = segment[:index]
            if len(prefix) >= 4:
                suffix = prefix[-2:]
                subjects.append(prefix if suffix in CJK_INTENT_TERMS else suffix)
            else:
                subjects.append(prefix)
            break
    return _dedupe(subjects)


def _format_terms(segments: list[str]) -> list[str]:
    terms: list[str] = []
    for segment in segments:
        for term in CJK_FORMAT_TERMS:
            if term in segment:
                terms.append(term)
    return _dedupe(terms)


def _intent_terms(segments: list[str]) -> list[str]:
    terms: list[str] = []
    for segment in segments:
        for term in CJK_INTENT_TERMS:
            if term in segment:
                terms.append(term)
    return _dedupe(terms)


def _keyword_query(query: str) -> str:
    parts: list[str] = []
    parts.extend(_numeric_terms(query))
    parts.extend(_latin_terms(query))
    parts.extend(_selected_cjk_terms(query))
    return " ".join(parts)


def _latin_focus_query(query: str) -> str:
    latin_terms = _latin_terms(query)
    if len(latin_terms) < 2:
        return ""
    cjk_terms = _selected_cjk_terms(query)[:4]
    return " ".join(latin_terms + cjk_terms)


def _numeric_terms(query: str) -> list[str]:
    return _dedupe(re.findall(r"(?<![a-zA-Z0-9])\d{1,6}(?![a-zA-Z0-9])", query or ""))


def _latin_terms(query: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z][a-zA-Z0-9._+-]*", query or "")
    return _dedupe(term.lower() for term in terms if len(term) > 1)


def _selected_cjk_terms(query: str) -> list[str]:
    selected: list[str] = []
    for term in _cjk_keyword_chunks(query):
        if term in selected:
            continue
        selected.append(term)
        if len(selected) >= 8:
            break
    return selected


def _cjk_keyword_chunks(query: str) -> list[str]:
    chunks: list[str] = []
    split_pattern = f"[{re.escape(''.join(_CJK_SPLIT_CHARS))}]+"
    for run in re.findall(r"[\u4e00-\u9fff]+", query or ""):
        for raw_chunk in re.split(split_pattern, run):
            chunk = raw_chunk.strip()
            if len(chunk) < 2:
                continue
            chunks.append(chunk[:12])
    return chunks


def _normalize_query(query: str) -> str:
    return " ".join(str(query or "").split()).strip()


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


_CJK_SPLIT_CHARS = set("的了和与及或是在为以对把将从这那而并就都很还要年")
