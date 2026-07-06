import json
from pathlib import Path

import pytest

from agent.search import SearchService, StaticSearchProvider
from agent.search.evaluation import (
    evaluate_search_case,
    load_search_eval_cases,
    result_matches_spec,
    summarize_search_eval,
)


SEARCH_EVAL_CASES = Path(__file__).resolve().parents[1] / "evals" / "search" / "cases.json"
TRACE_SEARCH_EVAL_CASES = Path(__file__).resolve().parents[1] / "evals" / "search" / "trace_cases.json"
SEARCH_QUERY_BANK = Path(__file__).resolve().parents[1] / "evals" / "search" / "query_bank.json"


def test_search_eval_matcher_supports_text_and_field_constraints():
    result = {
        "title": "Euro Truck Simulator 2 DLCs on Steam",
        "snippet": "Browse map expansions and cargo DLC packages.",
        "url": "https://store.steampowered.com/dlc/227300/Euro_Truck_Simulator_2/",
        "source": "fixture",
    }

    assert result_matches_spec(
        result,
        {
            "source": "fixture",
            "url_contains": "steampowered.com",
            "all_text_contains": ["Euro Truck Simulator 2", "DLC"],
        },
    )
    assert not result_matches_spec(
        result,
        {
            "all_text_contains": ["Euro Truck Simulator 2", "exchange rate"],
        },
    )


def test_trace_search_eval_cases_and_query_bank_are_loadable():
    cases = load_search_eval_cases(TRACE_SEARCH_EVAL_CASES)
    query_bank = json.loads(SEARCH_QUERY_BANK.read_text(encoding="utf-8"))

    assert len(cases) >= 1
    assert query_bank["query_count"] >= len(cases)
    assert all(case.get("trace", {}).get("run_id") for case in cases)
    assert all(case.get("fixture_results") for case in cases)


def test_search_eval_scores_recall_precision_mrr_and_bad_matches():
    case = {
        "id": "sample",
        "query": "成人钢琴入门 教材",
        "expected": [
            {"label": "piano", "all_text_contains": ["成人", "钢琴", "教材"]},
            {"label": "beyer", "all_text_contains": ["拜厄", "钢琴"]},
        ],
        "negative": [
            {"label": "adult-video", "any_text_contains": ["成人视频"]},
        ],
        "checks": {
            "k": 3,
            "min_recall_at_k": 1.0,
            "min_precision_at_k": 0.67,
            "min_mrr": 1.0,
            "max_bad_at_k": 0,
        },
    }
    results = [
        {
            "title": "成人钢琴入门教材推荐",
            "snippet": "拜厄钢琴基本教程和车尔尼练习。",
            "url": "https://example.com/piano",
            "source": "fixture",
        },
        {
            "title": "成人视频下载",
            "snippet": "污染结果。",
            "url": "https://example.com/adult-video",
            "source": "fixture",
        },
        {
            "title": "钢琴练习计划",
            "snippet": "成人学习钢琴的每日计划。",
            "url": "https://example.com/practice",
            "source": "fixture",
        },
    ]

    report = evaluate_search_case(case, results)

    assert report["metrics"]["recall_at_k"] == 1.0
    assert report["metrics"]["mrr"] == 1.0
    assert report["metrics"]["bad_at_k"] == 1
    assert not report["passed"]
    assert any("bad_at_k" in failure for failure in report["failures"])


@pytest.mark.asyncio
async def test_search_eval_fixture_suite_passes_offline():
    reports = []
    for case in load_search_eval_cases(SEARCH_EVAL_CASES):
        provider = StaticSearchProvider(
            name="fixture",
            documents=case["fixture_results"],
        )
        provider.recall_query_limit = int(
            case.get("fixture_recall_query_limit") or case.get("recall_max_queries") or 2
        )
        service = SearchService(
            [provider],
            reranker=None,
            retry_attempts=1,
            min_provider_coverage=1,
            provider_limit_multiplier=3,
            recall_max_queries=int(case.get("recall_max_queries") or 2),
            recall_timeout_seconds=1.0,
        )
        limit = int((case.get("checks") or {}).get("k") or 5)
        results = await service.search(case["query"], limit=limit)
        report = evaluate_search_case(
            case,
            results,
            latency_ms=0,
            trace_nodes=service.last_trace_nodes,
            provider_errors=service.last_provider_errors,
            checks_key="offline_checks",
        )
        reports.append(report)

    summary = summarize_search_eval(reports)

    assert summary["failed_count"] == 0, reports
    assert summary["case_count"] >= 5
    assert summary["mean_recall_at_k"] >= 0.67
    assert "total_bad_at_k" in summary
