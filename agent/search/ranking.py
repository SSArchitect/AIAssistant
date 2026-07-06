from __future__ import annotations

from dataclasses import dataclass
import math
import re
from urllib.parse import urlparse
from typing import Protocol


class SearchResultLike(Protocol):
    title: str
    snippet: str
    url: str
    source: str

BM25_K1 = 1.5
BM25_B = 0.75
DEFAULT_MIN_RANK_SCORE = 0.05
OFFICIAL_DOMAIN_BOOST = 1.25


@dataclass(frozen=True)
class RankedSearchResult:
    result: SearchResultLike
    score: float


def rank_search_results(
    query: str,
    results: list[SearchResultLike],
    *,
    min_score: float = DEFAULT_MIN_RANK_SCORE,
) -> list[RankedSearchResult]:
    query_terms = search_query_terms(query)
    if not query_terms:
        return [
            RankedSearchResult(result=result, score=1.0)
            for result in results
        ]

    documents = [_search_result_terms(result) for result in results]
    if len(results) == 1:
        score = _rank_score(
            query_terms=query_terms,
            result=results[0],
            document=documents[0],
            documents=documents,
        )
        return [RankedSearchResult(result=results[0], score=score)]

    ranked: list[RankedSearchResult] = []
    for result, document in zip(results, documents):
        score = _rank_score(
            query_terms=query_terms,
            result=result,
            document=document,
            documents=documents,
        )
        if score >= min_score:
            ranked.append(RankedSearchResult(result=result, score=score))

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def diversify_ranked_results(
    ranked: list[RankedSearchResult],
) -> list[RankedSearchResult]:
    if len(ranked) < 2:
        return ranked
    buckets: dict[str, list[RankedSearchResult]] = {}
    source_order: list[str] = []
    for item in ranked:
        source = getattr(item.result, "source", "") or _result_host(item.result)
        if source not in buckets:
            buckets[source] = []
            source_order.append(source)
        buckets[source].append(item)

    source_order.sort(key=lambda source: buckets[source][0].score, reverse=True)
    diversified: list[RankedSearchResult] = []
    while len(diversified) < len(ranked):
        progressed = False
        for source in source_order:
            if not buckets[source]:
                continue
            diversified.append(buckets[source].pop(0))
            progressed = True
        if not progressed:
            break
    return diversified


def _rank_score(
    *,
    query_terms: list[str],
    result: SearchResultLike,
    document: list[str],
    documents: list[list[str]],
) -> float:
    average_length = sum(len(document) for document in documents) / max(1, len(documents))
    document_frequencies = _document_frequencies(documents)
    score = _bm25_score(
        query_terms=query_terms,
        document=document,
        document_frequencies=document_frequencies,
        document_count=len(documents),
        average_length=average_length,
    )
    return score + _authority_boost(query_terms, result)


def search_query_terms(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    query = _split_latin_digit_boundaries(query or "")

    def add_term(term: str) -> None:
        term = term.strip().lower()
        if not _is_useful_term(term) or term in seen:
            return
        seen.add(term)
        terms.append(term)

    for raw in re.split(r"[\s,，;；/、|｜:：()（）\[\]【】\"'“”]+", query or ""):
        term = raw.strip().lower()
        if not term:
            continue
        if _has_cjk(term):
            for cjk_run in re.findall(r"[\u4e00-\u9fff]+", term):
                for cjk_term in _cjk_query_terms(cjk_run):
                    add_term(cjk_term)
            latin_parts = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", term)
            for part in latin_parts:
                add_term(part)
        else:
            add_term(term)
    return terms


def search_result_relevance_score(query: str, result: SearchResultLike) -> float:
    query_terms = search_query_terms(query)
    if not query_terms:
        return 0.0
    document = _search_result_terms(result)
    return _rank_score(
        query_terms=query_terms,
        result=result,
        document=document,
        documents=[document],
    )


def _search_result_terms(result: SearchResultLike) -> list[str]:
    terms: list[str] = []
    title_terms = _text_terms(result.title or "")
    snippet_terms = _text_terms(result.snippet or "")
    url_terms = _url_terms(result.url or "")
    terms.extend(title_terms * 3)
    terms.extend(snippet_terms)
    terms.extend(url_terms)
    return terms


def _text_terms(text: str) -> list[str]:
    terms: list[str] = []
    text = _split_latin_digit_boundaries(text or "")
    for raw in re.split(r"[\s,，;；/、|｜:：()（）\[\]【】\"'“”.!?！？#&+=<>]+", text or ""):
        term = raw.strip().lower()
        if not term:
            continue
        if _has_cjk(term):
            for cjk_run in re.findall(r"[\u4e00-\u9fff]+", term):
                terms.extend(cjk_term for cjk_term in _cjk_query_terms(cjk_run) if _is_useful_term(cjk_term))
            for part in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", term):
                if _is_useful_term(part):
                    terms.append(part.lower())
        elif _is_useful_term(term):
            terms.append(term)
    return terms


def _url_terms(url: str) -> list[str]:
    if not url:
        return []
    parsed = urlparse(url)
    text = " ".join(
        part
        for part in [
            parsed.netloc.replace(".", " ").replace("-", " "),
            parsed.path.replace("/", " ").replace("-", " ").replace("_", " "),
        ]
        if part
    )
    return _text_terms(text)


def _document_frequencies(documents: list[list[str]]) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for document in documents:
        for term in set(document):
            frequencies[term] = frequencies.get(term, 0) + 1
    return frequencies


def _bm25_score(
    *,
    query_terms: list[str],
    document: list[str],
    document_frequencies: dict[str, int],
    document_count: int,
    average_length: float,
) -> float:
    if not document or average_length <= 0:
        return 0.0
    term_counts: dict[str, int] = {}
    for term in document:
        term_counts[term] = term_counts.get(term, 0) + 1
    document_length = len(document)
    score = 0.0
    for term in query_terms:
        frequency = term_counts.get(term, 0)
        if frequency <= 0:
            continue
        document_frequency = document_frequencies.get(term, 0)
        idf = math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
        denominator = frequency + BM25_K1 * (1 - BM25_B + BM25_B * document_length / average_length)
        score += idf * (frequency * (BM25_K1 + 1)) / denominator
    return score


def _authority_boost(query_terms: list[str], result: SearchResultLike) -> float:
    host = urlparse(result.url or "").netloc.lower()
    if not host:
        return 0.0
    host = host[4:] if host.startswith("www.") else host
    compact_host = host.replace("-", "").replace(".", "")
    for term in query_terms:
        if _has_cjk(term) or len(term) < 4 or not term.isalpha():
            continue
        if term in compact_host:
            return OFFICIAL_DOMAIN_BOOST
    return 0.0


def _result_host(result: SearchResultLike) -> str:
    host = urlparse(result.url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _cjk_query_terms(term: str) -> list[str]:
    if len(term) <= 2:
        return [term]
    terms: list[str] = []
    max_n = min(4, len(term))
    for size in range(2, max_n + 1):
        for index in range(0, len(term) - size + 1):
            terms.append(term[index:index + size])
    return terms


def _is_useful_term(term: str) -> bool:
    if not term:
        return False
    if term.isdigit():
        return len(term) <= 6
    if len(term) <= 1:
        return False
    if len(term) <= 2 and not _has_cjk(term):
        return False
    return term not in _STOPWORDS


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _split_latin_digit_boundaries(text: str) -> str:
    return re.sub(
        r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])",
        " ",
        text or "",
    )


_STOPWORDS = {
    "a",
    "an",
    "and",
    "case",
    "for",
    "in",
    "latest",
    "news",
    "of",
    "recent",
    "study",
    "the",
    "trend",
    "trends",
    "update",
    "updates",
    "with",
}
