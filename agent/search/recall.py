from __future__ import annotations

import re

DEFAULT_RECALL_MAX_QUERIES = 2


def build_query_variants(
    query: str,
    *,
    max_queries: int = DEFAULT_RECALL_MAX_QUERIES,
) -> list[str]:
    max_queries = max(1, max_queries)
    original = _normalize_query(query)
    if not original:
        return []

    variants = [original]
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
    return variants


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
    return _dedupe(re.findall(r"(?<![a-zA-Z0-9])\d{2,6}(?![a-zA-Z0-9])", query or ""))


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
