from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any


class SearchEvalError(ValueError):
    """Raised when a search evaluation case is malformed."""


def load_search_eval_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise SearchEvalError("search eval payload must contain a cases list")
    normalized: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise SearchEvalError(f"case #{index} must be an object")
        case_id = str(case.get("id") or "").strip()
        query = str(case.get("query") or "").strip()
        if not case_id:
            raise SearchEvalError(f"case #{index} missing id")
        if not query:
            raise SearchEvalError(f"case {case_id} missing query")
        if not isinstance(case.get("expected"), list) or not case["expected"]:
            raise SearchEvalError(f"case {case_id} must define expected matches")
        normalized.append(case)
    return normalized


def evaluate_search_case(
    case: dict[str, Any],
    results: list[Any],
    *,
    latency_ms: int | None = None,
    trace_nodes: list[dict[str, Any]] | None = None,
    provider_errors: list[str] | None = None,
    checks_key: str = "checks",
) -> dict[str, Any]:
    checks = case.get(checks_key) if isinstance(case.get(checks_key), dict) else None
    if checks is None:
        checks = case.get("checks") if isinstance(case.get("checks"), dict) else {}
    k = _positive_int(checks.get("k"), default=5)
    top_results = results[:k]
    expected_specs = _specs(case.get("expected"))
    acceptable_specs = _specs(case.get("acceptable"))
    negative_specs = _specs(case.get("negative"))

    matched_expected: list[dict[str, Any]] = []
    for spec_index, spec in enumerate(expected_specs, start=1):
        rank = _first_match_rank(results, spec)
        if rank is None or rank > k:
            continue
        matched_expected.append(
            {
                "label": _spec_label(spec, f"expected_{spec_index}"),
                "rank": rank,
            }
        )

    relevant_ranks: list[int] = []
    bad_matches: list[dict[str, Any]] = []
    for rank, result in enumerate(top_results, start=1):
        if any(result_matches_spec(result, spec) for spec in [*expected_specs, *acceptable_specs]):
            relevant_ranks.append(rank)
        for spec_index, spec in enumerate(negative_specs, start=1):
            if result_matches_spec(result, spec):
                bad_matches.append(
                    {
                        "rank": rank,
                        "label": _spec_label(spec, f"negative_{spec_index}"),
                        "title": _field_value(result, "title"),
                        "url": _field_value(result, "url"),
                    }
                )

    first_expected_rank = min((item["rank"] for item in matched_expected), default=None)
    recall_at_k = len(matched_expected) / len(expected_specs)
    precision_at_k = len(relevant_ranks) / max(1, min(k, len(top_results)))
    mrr = 0.0 if first_expected_rank is None else 1.0 / first_expected_rank
    metrics = {
        "k": k,
        "result_count": len(results),
        "expected_count": len(expected_specs),
        "expected_found_at_k": len(matched_expected),
        "recall_at_k": recall_at_k,
        "precision_at_k": precision_at_k,
        "mrr": mrr,
        "bad_at_k": len(bad_matches),
    }
    if latency_ms is not None:
        metrics["latency_ms"] = latency_ms

    failures = _check_failures(
        checks=checks,
        metrics=metrics,
        bad_matches=bad_matches,
        latency_ms=latency_ms,
    )
    return {
        "id": case["id"],
        "query": case["query"],
        "category": case.get("category") or "",
        "passed": not failures,
        "failures": failures,
        "metrics": metrics,
        "matched_expected": matched_expected,
        "bad_matches": bad_matches,
        "top_results": [_result_preview(result) for result in top_results],
        "provider_errors": provider_errors or [],
        "trace_nodes": trace_nodes or [],
        "checks_key": checks_key if checks_key in case else "checks",
    }


def result_matches_spec(result: Any, spec: dict[str, Any]) -> bool:
    if not spec:
        return False
    checks = 0
    for field in ("title", "snippet", "url", "source"):
        expected = spec.get(f"{field}_contains")
        if expected is not None:
            checks += 1
            if _contains(_field_value(result, field), str(expected)):
                continue
            return False
    source = spec.get("source")
    if source is not None:
        checks += 1
        if _field_value(result, "source").lower() != str(source).strip().lower():
            return False
    all_text_contains = spec.get("all_text_contains")
    if all_text_contains is not None:
        terms = _string_list(all_text_contains)
        checks += 1
        blob = _result_text(result)
        if not terms or not all(_contains(blob, term) for term in terms):
            return False
    any_text_contains = spec.get("any_text_contains")
    if any_text_contains is not None:
        terms = _string_list(any_text_contains)
        checks += 1
        blob = _result_text(result)
        if not terms or not any(_contains(blob, term) for term in terms):
            return False
    return checks > 0


def summarize_search_eval(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [item for item in case_results if item.get("passed")]
    failed = [item for item in case_results if not item.get("passed")]
    metrics = [item.get("metrics", {}) for item in case_results]
    return {
        "case_count": len(case_results),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "pass_rate": len(passed) / max(1, len(case_results)),
        "mean_recall_at_k": _metric_mean(metrics, "recall_at_k"),
        "mean_precision_at_k": _metric_mean(metrics, "precision_at_k"),
        "mean_mrr": _metric_mean(metrics, "mrr"),
        "total_bad_at_k": sum(int(item.get("bad_at_k") or 0) for item in metrics),
        "mean_latency_ms": _metric_mean(metrics, "latency_ms"),
        "failed_cases": [str(item.get("id")) for item in failed],
    }


def _check_failures(
    *,
    checks: dict[str, Any],
    metrics: dict[str, Any],
    bad_matches: list[dict[str, Any]],
    latency_ms: int | None,
) -> list[str]:
    failures: list[str] = []
    min_recall = _float_or_none(checks.get("min_recall_at_k"))
    if min_recall is not None and float(metrics["recall_at_k"]) < min_recall:
        failures.append(
            f"recall_at_k {metrics['recall_at_k']:.3f} < {min_recall:.3f}"
        )
    min_precision = _float_or_none(checks.get("min_precision_at_k"))
    if min_precision is not None and float(metrics["precision_at_k"]) < min_precision:
        failures.append(
            f"precision_at_k {metrics['precision_at_k']:.3f} < {min_precision:.3f}"
        )
    min_mrr = _float_or_none(checks.get("min_mrr"))
    if min_mrr is not None and float(metrics["mrr"]) < min_mrr:
        failures.append(f"mrr {metrics['mrr']:.3f} < {min_mrr:.3f}")
    max_bad = _float_or_none(checks.get("max_bad_at_k"))
    if max_bad is not None and float(metrics["bad_at_k"]) > max_bad:
        labels = ", ".join(f"{item['label']}@{item['rank']}" for item in bad_matches)
        suffix = f": {labels}" if labels else ""
        failures.append(f"bad_at_k {metrics['bad_at_k']} > {int(max_bad)}{suffix}")
    max_latency = _float_or_none(checks.get("max_latency_ms"))
    if max_latency is not None and latency_ms is not None and latency_ms > max_latency:
        failures.append(f"latency_ms {latency_ms} > {int(max_latency)}")
    return failures


def _specs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first_match_rank(results: list[Any], spec: dict[str, Any]) -> int | None:
    for rank, result in enumerate(results, start=1):
        if result_matches_spec(result, spec):
            return rank
    return None


def _result_preview(result: Any) -> dict[str, str]:
    return {
        "title": _field_value(result, "title"),
        "url": _field_value(result, "url"),
        "source": _field_value(result, "source"),
        "snippet": _field_value(result, "snippet")[:180],
    }


def _field_value(result: Any, field: str) -> str:
    if isinstance(result, dict):
        return str(result.get(field) or "")
    return str(getattr(result, field, "") or "")


def _result_text(result: Any) -> str:
    return " ".join(
        _field_value(result, field)
        for field in ("title", "snippet", "url", "source")
    )


def _contains(text: str, needle: str) -> bool:
    return needle.strip().lower() in text.lower()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _spec_label(spec: dict[str, Any], fallback: str) -> str:
    return str(spec.get("label") or fallback)


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_mean(metrics: list[dict[str, Any]], key: str) -> float | None:
    values = [
        float(item[key])
        for item in metrics
        if key in item and item[key] is not None
    ]
    return mean(values) if values else None
