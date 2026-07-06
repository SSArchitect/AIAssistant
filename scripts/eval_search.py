#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.search import SearchService, StaticSearchProvider
from agent.search.evaluation import (
    evaluate_search_case,
    load_search_eval_cases,
    summarize_search_eval,
)
from agent.search.service import _rank_results_by_query_relevance


DEFAULT_CASES_PATH = ROOT / "evals" / "search" / "cases.json"


async def main() -> int:
    args = _parse_args()
    cases = load_search_eval_cases(args.cases)
    if args.case:
        wanted = set(args.case)
        cases = [case for case in cases if case["id"] in wanted]
    if not cases:
        print("No search eval cases selected.", file=sys.stderr)
        return 2

    case_reports: list[dict[str, Any]] = []
    for case in cases:
        case_reports.append(await _run_case(case, args))

    report = {
        "mode": args.mode,
        "case_file": str(Path(args.cases).resolve()),
        "summary": summarize_search_eval(case_reports),
        "cases": case_reports,
    }
    if args.compare_original:
        if args.mode != "offline":
            print("--compare-original is only supported in offline mode.", file=sys.stderr)
            return 2
        original_reports = [await _run_original_only_case(case, args) for case in cases]
        report["original_baseline"] = {
            "summary": summarize_search_eval(original_reports),
            "cases": original_reports,
        }
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human_report(report)
    return 0 if report["summary"]["failed_count"] == 0 or args.no_fail else 1


async def _run_case(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    checks_key = "offline_checks" if args.mode == "offline" else "checks"
    checks = case.get(checks_key) if isinstance(case.get(checks_key), dict) else case.get("checks") or {}
    limit = args.limit or int(checks.get("k") or 5)
    if args.endpoint:
        return await _run_endpoint_case(case, args, limit=limit, checks_key=checks_key)
    service = _service_for_case(case, args)
    started = perf_counter()
    results = await service.search(
        case["query"],
        sources=_sources(args.sources),
        limit=limit,
        open_results=args.open_results,
    )
    latency_ms = int((perf_counter() - started) * 1000)
    return evaluate_search_case(
        case,
        results,
        latency_ms=latency_ms,
        trace_nodes=service.last_trace_nodes,
        provider_errors=service.last_provider_errors,
        checks_key=checks_key,
    )


async def _run_original_only_case(
    case: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    checks = case.get("offline_checks") if isinstance(case.get("offline_checks"), dict) else case.get("checks") or {}
    limit = args.limit or int(checks.get("k") or 5)
    fixture_results = case.get("fixture_results")
    if not isinstance(fixture_results, list) or not fixture_results:
        raise SystemExit(f"case {case['id']} has no fixture_results for original-only comparison")
    provider = StaticSearchProvider(
        name="fixture",
        documents=[item for item in fixture_results if isinstance(item, dict)],
    )
    started = perf_counter()
    raw_results = await provider.search(case["query"], limit=max(limit, limit * 3))
    ranked_results = _rank_results_by_query_relevance(case["query"], raw_results)[:limit]
    latency_ms = int((perf_counter() - started) * 1000)
    return evaluate_search_case(
        case,
        ranked_results,
        latency_ms=latency_ms,
        checks_key="offline_checks",
    )


async def _run_endpoint_case(
    case: dict[str, Any],
    args: argparse.Namespace,
    *,
    limit: int,
    checks_key: str,
) -> dict[str, Any]:
    started = perf_counter()
    payload = await asyncio.to_thread(
        _post_search_endpoint,
        args.endpoint,
        {
            "query": case["query"],
            "sources": _sources(args.sources),
            "limit": limit,
            "open_results": args.open_results,
        },
        args.timeout,
    )
    latency_ms = int((perf_counter() - started) * 1000)
    return evaluate_search_case(
        case,
        payload.get("results") or [],
        latency_ms=latency_ms,
        trace_nodes=payload.get("trace_nodes") or [],
        provider_errors=payload.get("provider_errors") or [],
        checks_key=checks_key,
    )


def _post_search_endpoint(
    endpoint: str,
    body: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _service_for_case(case: dict[str, Any], args: argparse.Namespace) -> SearchService:
    if args.mode == "live":
        return SearchService.from_runtime_config()
    fixture_results = case.get("fixture_results")
    if not isinstance(fixture_results, list) or not fixture_results:
        raise SystemExit(f"case {case['id']} has no fixture_results for offline mode")
    provider = StaticSearchProvider(
        name="fixture",
        documents=[item for item in fixture_results if isinstance(item, dict)],
    )
    provider.recall_query_limit = int(case.get("fixture_recall_query_limit") or case.get("recall_max_queries") or 2)
    return SearchService(
        [
            provider
        ],
        reranker=None,
        retry_attempts=1,
        min_provider_coverage=1,
        provider_limit_multiplier=3,
        recall_max_queries=int(case.get("recall_max_queries") or 2),
        recall_timeout_seconds=1.0,
    )


def _sources(value: str) -> list[str] | None:
    sources = [item.strip() for item in value.split(",") if item.strip()]
    return sources or None


def _print_human_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "Search eval "
        f"mode={report['mode']} "
        f"passed={summary['passed_count']}/{summary['case_count']} "
        f"mean_recall@k={_fmt(summary['mean_recall_at_k'])} "
        f"mean_precision@k={_fmt(summary['mean_precision_at_k'])} "
        f"mean_mrr={_fmt(summary['mean_mrr'])} "
        f"total_bad@k={summary['total_bad_at_k']}"
    )
    if summary.get("mean_latency_ms") is not None:
        print(f"mean_latency_ms={int(summary['mean_latency_ms'])}")
    original_baseline = report.get("original_baseline")
    if isinstance(original_baseline, dict):
        baseline = original_baseline.get("summary") or {}
        print(
            "Original-only baseline "
            f"passed={baseline.get('passed_count')}/{baseline.get('case_count')} "
            f"mean_recall@k={_fmt(baseline.get('mean_recall_at_k'))} "
            f"mean_precision@k={_fmt(baseline.get('mean_precision_at_k'))} "
            f"total_bad@k={baseline.get('total_bad_at_k')}"
        )
    for case in report["cases"]:
        metrics = case["metrics"]
        status = "PASS" if case["passed"] else "FAIL"
        print(
            f"{status} {case['id']} "
            f"checks={case.get('checks_key', 'checks')} "
            f"recall@{metrics['k']}={metrics['recall_at_k']:.3f} "
            f"precision@{metrics['k']}={metrics['precision_at_k']:.3f} "
            f"mrr={metrics['mrr']:.3f} "
            f"bad@{metrics['k']}={metrics['bad_at_k']} "
            f"latency_ms={metrics.get('latency_ms', '-')}"
        )
        for failure in case["failures"]:
            print(f"  - {failure}")


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{float(value):.3f}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the search quality eval suite.")
    parser.add_argument(
        "--cases",
        default=str(DEFAULT_CASES_PATH),
        help="Path to search eval cases JSON.",
    )
    parser.add_argument(
        "--mode",
        choices=("offline", "live"),
        default="offline",
        help="offline uses fixture_results; live uses configured search providers.",
    )
    parser.add_argument(
        "--case",
        action="append",
        help="Run only a specific case id. Can be passed multiple times.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Override result limit.")
    parser.add_argument(
        "--sources",
        default="",
        help="Comma-separated provider sources for live mode, e.g. web,bing-rss.",
    )
    parser.add_argument(
        "--open-results",
        action="store_true",
        help="Open top result pages during search. Usually keep false for search evals.",
    )
    parser.add_argument(
        "--endpoint",
        default="",
        help="POST /agent/search endpoint to evaluate, e.g. http://127.0.0.1:9090/agent/search.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45,
        help="HTTP timeout in seconds when --endpoint is used.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    parser.add_argument("--output", help="Write full JSON report to a file.")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0 even when quality checks fail.",
    )
    parser.add_argument(
        "--compare-original",
        action="store_true",
        help="In offline mode, also score an original-query-only baseline.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
