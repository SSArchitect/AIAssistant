#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any
from urllib.parse import quote
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_DB = ROOT / "data" / "assistant.db"
DEFAULT_SERVER_BASE_URL = "http://49.235.143.82"
DEFAULT_CASE_OUTPUT = ROOT / "evals" / "search" / "trace_cases.json"
DEFAULT_QUERY_BANK_OUTPUT = ROOT / "evals" / "search" / "query_bank.json"

CASE_VERSION = 1
QUERY_BANK_VERSION = 1
MAX_SNIPPET_CHARS = 420
MAX_FIXTURE_RESULTS = 12
MAX_EXPECTED = 3
MAX_NEGATIVE = 3


def main() -> int:
    args = _parse_args()
    trace_records: list[dict[str, Any]] = []

    if args.local_db:
        trace_records.extend(_load_local_trace_records(Path(args.local_db)))
    if args.server_base_url:
        trace_records.extend(
            _load_server_trace_records(
                args.server_base_url.rstrip("/"),
                max_conversations=args.max_server_conversations,
                timeout=args.server_timeout,
            )
        )

    search_calls = _extract_search_calls(trace_records)
    query_bank = _build_query_bank(trace_records, search_calls)
    cases, skipped = _build_cases(search_calls, max_cases=args.max_cases)

    _write_json(
        Path(args.output),
        {
            "version": CASE_VERSION,
            "generated_at": _utc_now(),
            "description": (
                "Trace-derived search eval cases collected from local/server search traces. "
                "These are broad regression fixtures with pseudo labels from historical LLM rerank "
                "decisions; keep curated hand-labeled cases in evals/search/cases.json for stricter checks."
            ),
            "case_count": len(cases),
            "source_counts": dict(Counter(case["trace"]["source"] for case in cases)),
            "skipped_counts": dict(skipped),
            "cases": cases,
        },
    )
    if args.query_bank_output:
        _write_json(
            Path(args.query_bank_output),
            {
                "version": QUERY_BANK_VERSION,
                "generated_at": _utc_now(),
                "description": (
                    "Deduplicated search query bank collected from local/server traces. "
                    "This file intentionally contains unlabeled query distribution data for future eval curation."
                ),
                "query_count": len(query_bank),
                "source_counts": _query_bank_source_counts(query_bank),
                "kind_counts": _query_bank_kind_counts(query_bank),
                "queries": query_bank,
            },
        )

    print(
        "Collected search eval data "
        f"trace_records={len(trace_records)} "
        f"search_calls={len(search_calls)} "
        f"cases={len(cases)} "
        f"query_bank={len(query_bank)} "
        f"skipped={dict(skipped)}"
    )
    print(f"Wrote cases: {Path(args.output).resolve()}")
    if args.query_bank_output:
        print(f"Wrote query bank: {Path(args.query_bank_output).resolve()}")
    return 0


def _load_local_trace_records(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        print(f"local db not found, skipping: {db_path}", file=sys.stderr)
        return []

    records: list[dict[str, Any]] = []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select id, conversation_id, run_id, created_at, trace_events
            from messages
            where trace_events is not null and trace_events != ''
            order by created_at desc
            """
        )
        for row in rows:
            meta = {
                "source": "local",
                "message_id": str(row["id"] or ""),
                "conversation_id": str(row["conversation_id"] or ""),
                "run_id": str(row["run_id"] or ""),
                "created_at": str(row["created_at"] or ""),
            }
            for event in _load_trace_events(row["trace_events"]):
                records.append({**meta, "event": event})
    finally:
        conn.close()
    return records


def _load_server_trace_records(
    base_url: str,
    *,
    max_conversations: int,
    timeout: float,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        conversations_payload = _fetch_json(f"{base_url}/api/conversations", timeout=timeout)
    except Exception as exc:
        print(f"server conversations fetch failed, skipping: {exc}", file=sys.stderr)
        return records

    conversations = _conversation_items(conversations_payload)
    if max_conversations > 0:
        conversations = conversations[:max_conversations]

    for conversation in conversations:
        conversation_id = str(
            conversation.get("id")
            or conversation.get("conversation_id")
            or ""
        ).strip()
        if not conversation_id:
            continue
        url = f"{base_url}/api/conversations/{quote(conversation_id, safe='')}?include_trace=1"
        try:
            detail = _fetch_json(url, timeout=timeout)
        except Exception as exc:
            print(
                f"server conversation fetch failed, skipping {conversation_id}: {exc}",
                file=sys.stderr,
            )
            continue
        for message in _message_items(detail):
            meta = {
                "source": "server",
                "message_id": str(message.get("id") or ""),
                "conversation_id": conversation_id,
                "run_id": str(message.get("run_id") or ""),
                "created_at": str(message.get("created_at") or ""),
            }
            for event in _load_trace_events(message.get("trace_events")):
                records.append({**meta, "event": event})
    return records


def _extract_search_calls(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: OrderedDict[tuple[str, str, str, str], dict[str, Any]] = OrderedDict()
    fallback_index = 0
    for record in records:
        event = record.get("event") or {}
        event_type = str(event.get("type") or "")
        payload = _dictish(event.get("payload"))
        is_search_tool = event_type == "tool.started" and payload.get("name") == "search"
        is_search_node = event_type.startswith("search.")
        is_tool_completed = event_type == "tool.completed" and (
            payload.get("name") == "search" or _result_preview_mentions_search(payload)
        )
        if not (is_search_tool or is_search_node or is_tool_completed):
            continue

        step_id = str(event.get("step_id") or payload.get("step_id") or "").strip()
        if not step_id:
            fallback_index += 1
            step_id = f"missing_step_{fallback_index}"
        run_id = str(event.get("run_id") or record.get("run_id") or "").strip()
        key = (
            str(record.get("source") or ""),
            run_id,
            str(record.get("message_id") or ""),
            step_id,
        )
        call = calls.setdefault(
            key,
            {
                "source": record.get("source") or "",
                "message_id": record.get("message_id") or "",
                "conversation_id": record.get("conversation_id") or "",
                "run_id": run_id,
                "created_at": record.get("created_at") or "",
                "step_id": step_id,
                "event_types": [],
                "tool_query": "",
                "original_query": "",
                "rewrite_queries": [],
                "rewrite_policy_id": "",
                "rewrite_strategy": "",
                "recall": {},
                "ranking_query": "",
                "ranking_results": [],
                "rerank": {},
            },
        )
        call["event_types"].append(event_type)

        if is_search_tool:
            arguments = _dictish(payload.get("arguments"))
            call["tool_query"] = _clean_text(arguments.get("query") or call["tool_query"])
            continue
        if event_type == "search.query_rewrite.completed":
            call["original_query"] = _clean_text(
                payload.get("original_query") or call["original_query"]
            )
            call["rewrite_queries"] = _string_list(payload.get("queries"))
            call["rewrite_policy_id"] = _clean_text(payload.get("policy_id"))
            call["rewrite_strategy"] = _clean_text(payload.get("strategy"))
            continue
        if event_type in {"search.recall.completed", "search.recall.partial"}:
            current = call.get("recall") if isinstance(call.get("recall"), dict) else {}
            call["recall"] = _better_recall_payload(current, payload)
            continue
        if event_type == "search.ranking.completed":
            call["ranking_query"] = _clean_text(payload.get("query") or call["ranking_query"])
            call["ranking_results"] = _list_of_dicts(payload.get("top_results"))
            continue
        if event_type == "search.llm_rerank.completed":
            call["rerank"] = {
                "threshold": _float_or_none(payload.get("threshold")),
                "decisions": _list_of_dicts(payload.get("decisions")),
                "top_results": _list_of_dicts(payload.get("top_results")),
                "model": _clean_text(payload.get("model")),
                "provider": _clean_text(payload.get("provider")),
                "duration_ms": _int_or_none(payload.get("duration_ms")),
                "kept_count": _int_or_none(payload.get("kept_count")),
                "candidate_count": _int_or_none(payload.get("candidate_count")),
            }
            continue
    return list(calls.values())


def _build_cases(
    calls: list[dict[str, Any]],
    *,
    max_cases: int,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    cases: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    seen_queries: set[str] = set()

    sorted_calls = sorted(
        calls,
        key=lambda call: (
            0 if call.get("source") == "server" else 1,
            str(call.get("created_at") or ""),
        ),
        reverse=False,
    )
    for call in sorted_calls:
        query = _case_query(call)
        normalized_query = _normalize_query(query)
        if not query:
            skipped["missing_query"] += 1
            continue
        if normalized_query in seen_queries:
            skipped["duplicate_query"] += 1
            continue
        case = _case_from_call(call)
        if case is None:
            skipped["unlabeled_or_incomplete"] += 1
            continue
        seen_queries.add(normalized_query)
        cases.append(case)
        if max_cases > 0 and len(cases) >= max_cases:
            break
    return cases, skipped


def _case_from_call(call: dict[str, Any]) -> dict[str, Any] | None:
    query = _case_query(call)
    ranking_results = _list_of_dicts(call.get("ranking_results"))
    rerank = call.get("rerank") if isinstance(call.get("rerank"), dict) else {}
    decisions = _normalize_decisions(rerank.get("decisions"))
    if not query or not ranking_results or not decisions:
        return None

    threshold = _float_or_none(rerank.get("threshold"))
    min_expected_score = max(0.5, threshold or 0.5)
    expected_decisions = [
        decision for decision in decisions if decision["score"] >= min_expected_score
    ][:MAX_EXPECTED]
    negative_decisions = [
        decision
        for decision in reversed(decisions)
        if decision["score"] <= min(0.2, (threshold or 0.5) - 0.25)
    ][:MAX_NEGATIVE]
    if not expected_decisions:
        return None

    fixture_results = _fixture_results(
        query=query,
        ranking_results=ranking_results,
        decisions=decisions,
    )
    if not fixture_results:
        return None

    expected = [
        _match_spec_from_decision(decision, f"expected_{index}")
        for index, decision in enumerate(expected_decisions, start=1)
    ]
    negative = [
        _match_spec_from_decision(decision, f"negative_{index}")
        for index, decision in enumerate(negative_decisions, start=1)
    ]

    case_id = _case_id(call, query)
    recall_queries = _string_list(call.get("rewrite_queries")) or [query]
    recall = call.get("recall") if isinstance(call.get("recall"), dict) else {}
    attempts = _list_of_dicts(recall.get("attempts"))
    case = {
        "id": case_id,
        "category": _infer_category(query),
        "query": query,
        "notes": (
            "Trace-derived pseudo-labeled case. Expected/negative labels come from "
            "historical search.llm_rerank decisions, not hand curation."
        ),
        "checks": _trace_checks(len(expected), len(negative)),
        "offline_checks": _trace_checks(len(expected), len(negative)),
        "expected": expected,
        "negative": negative,
        "fixture_recall_query_limit": max(1, min(4, len(recall_queries))),
        "recall_max_queries": max(1, min(4, len(recall_queries))),
        "fixture_results": fixture_results,
        "trace": {
            "source": call.get("source") or "",
            "run_id": call.get("run_id") or "",
            "conversation_id": call.get("conversation_id") or "",
            "message_id": call.get("message_id") or "",
            "step_id": call.get("step_id") or "",
            "created_at": call.get("created_at") or "",
            "rewrite_strategy": call.get("rewrite_strategy") or "",
            "rewrite_policy_id": call.get("rewrite_policy_id") or "",
            "rewrite_queries": recall_queries,
            "providers": _string_list(recall.get("providers")),
            "attempt_count": len(attempts),
            "timed_out_count": _int_or_none(recall.get("timed_out_count")) or 0,
            "rerank_threshold": threshold,
            "rerank_model": rerank.get("model") or "",
            "rerank_provider": rerank.get("provider") or "",
        },
    }
    return case


def _fixture_results(
    *,
    query: str,
    ranking_results: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_url: OrderedDict[str, dict[str, Any]] = OrderedDict()
    ranking_by_rank: dict[int, dict[str, Any]] = {}

    for result in ranking_results[:MAX_FIXTURE_RESULTS]:
        title = _clean_text(result.get("title"))
        url = _clean_text(result.get("url"))
        if not title and not url:
            continue
        rank = _int_or_none(result.get("rank"))
        if rank is not None:
            ranking_by_rank[rank] = result
        key = _fixture_key(title, url)
        retrieval_query = _clean_text(result.get("retrieval_query"))
        by_url[key] = {
            "title": title or url or "Untitled",
            "snippet": _snippet(
                query=query,
                retrieval_query=retrieval_query,
                reason="",
                score=None,
            ),
            "url": url,
            "source": _clean_text(result.get("source") or "trace"),
            "metadata": {
                "trace_rank": rank,
                "retrieval_query": retrieval_query,
                "retrieval_query_index": _int_or_none(result.get("retrieval_query_index")),
            },
        }

    for decision in decisions:
        title = decision["title"]
        url = decision["url"]
        if not title and not url:
            continue
        rank_result = ranking_by_rank.get(decision["index"]) or {}
        key = _fixture_key(title, url)
        retrieval_query = _clean_text(rank_result.get("retrieval_query"))
        existing = by_url.get(key) or {}
        metadata = dict(existing.get("metadata") or {})
        metadata.update(
            {
                "rerank_score": decision["score"],
                "rerank_reason": decision["reason"],
            }
        )
        if decision["index"]:
            metadata.setdefault("trace_rank", decision["index"])
        by_url[key] = {
            "title": title or existing.get("title") or url or "Untitled",
            "snippet": _snippet(
                query=query,
                retrieval_query=retrieval_query,
                reason=decision["reason"],
                score=decision["score"],
            ),
            "url": url or existing.get("url") or "",
            "source": _clean_text(existing.get("source") or rank_result.get("source") or "trace"),
            "metadata": metadata,
        }

    return list(by_url.values())[:MAX_FIXTURE_RESULTS]


def _build_query_bank(
    records: list[dict[str, Any]],
    calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for call in calls:
        query = _case_query(call)
        if query:
            _add_query_bank_entry(
                entries,
                query=query,
                kind="search_tool_query",
                source=str(call.get("source") or ""),
                run_id=str(call.get("run_id") or ""),
                conversation_id=str(call.get("conversation_id") or ""),
                step_id=str(call.get("step_id") or ""),
                created_at=str(call.get("created_at") or ""),
                parent_query="",
            )
        for rewritten in _string_list(call.get("rewrite_queries")):
            if not rewritten or _normalize_query(rewritten) == _normalize_query(query):
                continue
            _add_query_bank_entry(
                entries,
                query=rewritten,
                kind="rewrite_query",
                source=str(call.get("source") or ""),
                run_id=str(call.get("run_id") or ""),
                conversation_id=str(call.get("conversation_id") or ""),
                step_id=str(call.get("step_id") or ""),
                created_at=str(call.get("created_at") or ""),
                parent_query=query,
            )

    for record in records:
        event = record.get("event") or {}
        event_type = str(event.get("type") or "")
        payload = _dictish(event.get("payload"))
        if event_type in {"research.search.started", "research.search.completed"}:
            _add_query_bank_entry(
                entries,
                query=_clean_text(payload.get("query")),
                kind="research_search_query",
                source=str(record.get("source") or ""),
                run_id=str(event.get("run_id") or record.get("run_id") or ""),
                conversation_id=str(record.get("conversation_id") or ""),
                step_id=str(event.get("step_id") or ""),
                created_at=str(record.get("created_at") or ""),
                parent_query="",
            )
        elif event_type == "research.queries.created":
            for query in _queries_from_research_payload(payload):
                _add_query_bank_entry(
                    entries,
                    query=query,
                    kind="research_planned_query",
                    source=str(record.get("source") or ""),
                    run_id=str(event.get("run_id") or record.get("run_id") or ""),
                    conversation_id=str(record.get("conversation_id") or ""),
                    step_id=str(event.get("step_id") or ""),
                    created_at=str(record.get("created_at") or ""),
                    parent_query="",
                )

    return sorted(
        entries.values(),
        key=lambda item: (
            -int(item.get("count") or 0),
            str(item.get("query") or "").lower(),
        ),
    )


def _add_query_bank_entry(
    entries: OrderedDict[str, dict[str, Any]],
    *,
    query: str,
    kind: str,
    source: str,
    run_id: str,
    conversation_id: str,
    step_id: str,
    created_at: str,
    parent_query: str,
) -> None:
    query = _clean_text(query)
    if not query:
        return
    key = _normalize_query(query)
    if not key:
        return
    entry = entries.setdefault(
        key,
        {
            "query": query,
            "normalized_query": key,
            "count": 0,
            "sources": {},
            "kinds": {},
            "first_seen": created_at,
            "last_seen": created_at,
            "examples": [],
        },
    )
    entry["count"] = int(entry.get("count") or 0) + 1
    _counter_dict_increment(entry["sources"], source or "unknown")
    _counter_dict_increment(entry["kinds"], kind)
    if created_at:
        if not entry.get("first_seen") or created_at < str(entry.get("first_seen")):
            entry["first_seen"] = created_at
        if not entry.get("last_seen") or created_at > str(entry.get("last_seen")):
            entry["last_seen"] = created_at
    examples = entry.setdefault("examples", [])
    if len(examples) < 4:
        example = {
            "source": source,
            "kind": kind,
            "run_id": run_id,
            "conversation_id": conversation_id,
            "step_id": step_id,
            "created_at": created_at,
        }
        if parent_query:
            example["parent_query"] = parent_query
        examples.append(example)


def _match_spec_from_decision(decision: dict[str, Any], fallback_label: str) -> dict[str, Any]:
    title = decision.get("title") or fallback_label
    url = decision.get("url") or ""
    spec: dict[str, Any] = {"label": _truncate(title, 90)}
    if url:
        spec["url_contains"] = _url_match_fragment(url)
    elif title:
        spec["title_contains"] = _truncate(title, 60)
    return spec


def _trace_checks(expected_count: int, negative_count: int) -> dict[str, Any]:
    return {
        "k": 5,
        "min_recall_at_k": 1.0 if expected_count <= 1 else 0.5,
        "min_precision_at_k": 0.2,
        "min_mrr": 0.2,
        "max_bad_at_k": min(2, max(0, negative_count)),
        "max_latency_ms": 15000,
    }


def _case_query(call: dict[str, Any]) -> str:
    return _clean_text(
        call.get("original_query")
        or call.get("tool_query")
        or call.get("ranking_query")
    )


def _case_id(call: dict[str, Any], query: str) -> str:
    source = re.sub(r"[^a-z0-9]+", "_", str(call.get("source") or "trace").lower()).strip("_")
    slug = _slug(query) or "query"
    digest_source = "|".join(
        [
            str(call.get("run_id") or ""),
            str(call.get("step_id") or ""),
            query,
        ]
    )
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:8]
    return f"trace_{source}_{digest}_{slug[:44]}"


def _infer_category(query: str) -> str:
    lower = query.lower()
    if any(term in lower for term in ("euro truck", "gta", "simulator", "steam", "dlc")):
        return "game"
    if any(term in lower for term in ("dunlop", "sku", "formula 65")):
        return "product"
    if any(term in lower for term in ("ai", "llm", "gpt", "rag", "agent")):
        return "ai_research"
    if any(term in lower for term in ("2026", "today", "news", "latest")):
        return "current_info"
    if "course" in lower:
        return "learning_material"
    return "trace_derived"


def _better_recall_payload(current: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not current:
        return dict(payload)
    current_complete = current.get("status") == "completed"
    next_complete = payload.get("status") == "completed"
    if next_complete and not current_complete:
        return dict(payload)
    current_count = _int_or_none(current.get("result_count")) or 0
    next_count = _int_or_none(payload.get("result_count")) or 0
    if next_count >= current_count:
        return dict(payload)
    return current


def _normalize_decisions(value: Any) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for item in _list_of_dicts(value):
        score = _float_or_none(item.get("score"))
        if score is None:
            continue
        decisions.append(
            {
                "index": _int_or_none(item.get("index")) or 0,
                "score": score,
                "title": _clean_text(item.get("title")),
                "url": _clean_text(item.get("url")),
                "reason": _clean_text(item.get("reason")),
            }
        )
    decisions.sort(key=lambda item: item["score"], reverse=True)
    return decisions


def _snippet(
    *,
    query: str,
    retrieval_query: str,
    reason: str,
    score: float | None,
) -> str:
    parts = []
    include_query_context = score is None or score >= 0.45
    if retrieval_query and include_query_context:
        parts.append(f"retrieval query: {retrieval_query}")
    if reason:
        prefix = "" if score is None else f"rerank score {score:.2f}: "
        parts.append(f"{prefix}{reason}")
    if query and include_query_context:
        parts.append(f"original query: {query}")
    return _truncate(" | ".join(parts), MAX_SNIPPET_CHARS)


def _queries_from_research_payload(payload: dict[str, Any]) -> list[str]:
    queries: list[str] = []
    for value in (payload.get("queries"), payload.get("search_queries"), payload.get("items")):
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    queries.append(item)
                elif isinstance(item, dict):
                    query = item.get("query") or item.get("q") or item.get("search_query")
                    if query:
                        queries.append(str(query))
    query = payload.get("query")
    if query:
        queries.append(str(query))
    return [_clean_text(query) for query in queries if _clean_text(query)]


def _query_bank_source_counts(query_bank: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for entry in query_bank:
        for source, count in (entry.get("sources") or {}).items():
            counts[str(source)] += int(count or 0)
    return dict(counts)


def _query_bank_kind_counts(query_bank: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for entry in query_bank:
        for kind, count in (entry.get("kinds") or {}).items():
            counts[str(kind)] += int(count or 0)
    return dict(counts)


def _counter_dict_increment(mapping: dict[str, Any], key: str) -> None:
    mapping[key] = int(mapping.get(key) or 0) + 1


def _conversation_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("conversations", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _message_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("messages", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    conversation = payload.get("conversation")
    if isinstance(conversation, dict):
        value = conversation.get("messages")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _load_trace_events(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        events = raw.get("events")
        if isinstance(events, list):
            return [item for item in events if isinstance(item, dict)]
        return []
    if not isinstance(raw, str):
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return _load_trace_events(payload)


def _dictish(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    strings: list[str] = []
    for item in value:
        if isinstance(item, str):
            cleaned = _clean_text(item)
        elif isinstance(item, dict):
            cleaned = _clean_text(item.get("query") or item.get("q") or item.get("text"))
        else:
            cleaned = ""
        if cleaned and cleaned not in strings:
            strings.append(cleaned)
    return strings


def _fetch_json(url: str, *, timeout: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_query(value: str) -> str:
    return re.sub(r"\s+", " ", _clean_text(value).lower())


def _truncate(value: str, limit: int) -> str:
    value = _clean_text(value)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _slug(value: str) -> str:
    parts = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", value.lower())
    return "_".join(parts[:8])


def _fixture_key(title: str, url: str) -> str:
    return url.strip().lower() or title.strip().lower()


def _url_match_fragment(url: str) -> str:
    url = _clean_text(url)
    return url[:220]


def _result_preview_mentions_search(payload: dict[str, Any]) -> bool:
    preview = str(payload.get("result_preview") or payload.get("result") or "")
    return '"query_rewrite"' in preview or '"results"' in preview


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect local/server search traces into trace-derived eval fixtures."
    )
    parser.add_argument(
        "--local-db",
        default=str(DEFAULT_LOCAL_DB),
        help="Local assistant SQLite DB. Pass an empty string to skip local collection.",
    )
    parser.add_argument(
        "--server-base-url",
        default=DEFAULT_SERVER_BASE_URL,
        help="Server base URL. Pass an empty string to skip server collection.",
    )
    parser.add_argument(
        "--max-server-conversations",
        type=int,
        default=0,
        help="Maximum server conversations to scan; 0 scans all returned conversations.",
    )
    parser.add_argument(
        "--server-timeout",
        type=float,
        default=15.0,
        help="HTTP timeout per server request in seconds.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=80,
        help="Maximum trace-derived eval cases to write; 0 means no limit.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_CASE_OUTPUT),
        help="Output JSON path for trace-derived eval cases.",
    )
    parser.add_argument(
        "--query-bank-output",
        default=str(DEFAULT_QUERY_BANK_OUTPUT),
        help="Output JSON path for deduplicated query bank. Pass an empty string to skip.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
