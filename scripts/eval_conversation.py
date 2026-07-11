#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.eval.conversation import (  # noqa: E402
    CASE_VERSION,
    evaluate_conversation_case,
    load_conversation_eval_cases,
    summarize_conversation_eval,
    utc_now,
)


DEFAULT_CASES = ROOT / "evals" / "conversation" / "cases.json"


async def main() -> int:
    args = _parse_args()
    cases = load_conversation_eval_cases(args.cases)
    if args.case:
        wanted = set(args.case)
        cases = [case for case in cases if case["id"] in wanted]
    if not cases:
        report = {
            "version": CASE_VERSION,
            "generated_at": utc_now(),
            "mode": args.mode,
            "case_file": str(Path(args.cases).resolve()),
            "replay": _replay_metadata(args),
            "summary": summarize_conversation_eval([]),
            "cases": [],
        }
        if args.output:
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_human_report(report)
        return 0

    reports = []
    for case in cases:
        reports.append(await _run_case(case, args))

    report = {
        "version": CASE_VERSION,
        "generated_at": utc_now(),
        "mode": args.mode,
        "case_file": str(Path(args.cases).resolve()),
        "replay": _replay_metadata(args),
        "summary": summarize_conversation_eval(reports),
        "cases": reports,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human_report(report)
    return 0 if report["summary"]["failed_count"] == 0 or args.no_fail else 1


async def _run_case(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if args.mode == "historical":
        return evaluate_conversation_case(case)
    if args.mode == "agent":
        return await _run_agent_case(case, args)
    raise AssertionError(f"unknown mode {args.mode}")


async def _run_agent_case(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    input_payload = case.get("input") if isinstance(case.get("input"), dict) else {}
    messages = input_payload.get("messages") if isinstance(input_payload.get("messages"), list) else []
    user_messages = [item for item in messages if isinstance(item, dict) and item.get("role") == "user"]
    if not user_messages:
        raise SystemExit(f"case {case.get('id')} has no user input")
    message = str(user_messages[-1].get("content") or "")
    context_blocks = _replay_context_blocks(messages)
    body = {
        "conversation_id": f"eval_{case.get('id')}",
        "user_id": args.user_id,
        "message": message,
        "agent_id": input_payload.get("agent_id") or "super_chat",
        "model_preference": args.model_preference or None,
        "context_blocks": context_blocks,
        "memory_enabled": False,
        "disabled_tools": input_payload.get("disabled_tools") or [],
    }
    started = perf_counter()
    payload = await asyncio.to_thread(_post_json, args.endpoint, body, args.timeout)
    latency_ms = int((perf_counter() - started) * 1000)
    result = evaluate_conversation_case(
        case,
        response_text=payload.get("response") or "",
        skills_used=payload.get("skills_used") or [],
        events=payload.get("events") or [],
    )
    result["metrics"]["latency_ms"] = latency_ms
    result["run_id"] = payload.get("run_id") or ""
    result["model_used"] = payload.get("model_used") or ""
    result["response"] = {
        **(result.get("response") if isinstance(result.get("response"), dict) else {}),
        "content": payload.get("response") or "",
        "skills_used": payload.get("skills_used") or [],
        "model_used": payload.get("model_used") or "",
        "run_id": payload.get("run_id") or "",
    }
    result["replay"] = {
        "user_id": args.user_id,
        "conversation_id": body["conversation_id"],
        "endpoint": args.endpoint,
        "memory_enabled": False,
        "context_block_count": len(context_blocks),
    }
    return result


def _replay_context_blocks(messages: list[dict[str, Any]]) -> list[str]:
    prior = [item for item in messages[:-1] if isinstance(item, dict) and item.get("role") in {"user", "assistant"}]
    if not prior:
        return []
    lines = ["Eval replay context (prior messages, oldest to newest):"]
    for item in prior[-8:]:
        content = " ".join(str(item.get("content") or "").split()).strip()
        if content:
            lines.append(f"{item.get('role')}: {content[:1600]}")
    return ["\n".join(lines)] if len(lines) > 1 else []


def _replay_metadata(args: argparse.Namespace) -> dict[str, Any]:
    if args.mode != "agent":
        return {
            "kind": "historical",
            "uses_stored_response": True,
            "isolated_user_id": "",
        }
    return {
        "kind": "agent",
        "uses_stored_response": False,
        "endpoint": args.endpoint,
        "isolated_user_id": args.user_id,
        "memory_enabled": False,
    }


def _post_json(endpoint: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _print_human_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "Conversation eval "
        f"mode={report['mode']} "
        f"passed={summary['passed_count']}/{summary['case_count']} "
        f"pass_rate={summary['pass_rate']:.3f} "
        f"score={_fmt(summary.get('mean_overall_score'))} "
        f"mean_include={_fmt(summary.get('mean_must_include_ratio'))} "
        f"forbidden={summary['total_forbidden_present']} "
        f"missing_tools={summary['total_required_tool_missing']}"
    )
    for case in report["cases"]:
        status = "PASS" if case["passed"] else "FAIL"
        print(f"{status} {case['id']} intent={case.get('intent') or '-'} scenario={case.get('scenario') or '-'}")
        for failure in case.get("failures") or []:
            print(f"  - {failure}")


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{float(value):.3f}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run conversation eval cases.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Path to conversation cases JSON.")
    parser.add_argument("--mode", choices=("historical", "agent"), default="historical")
    parser.add_argument("--case", action="append", help="Run only a specific case id. Can be passed multiple times.")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9090/agent/chat", help="Agent chat endpoint for --mode agent.")
    parser.add_argument("--model-preference", default="", help="Optional model preference for agent mode.")
    parser.add_argument("--user-id", default="__eval__", help="Isolated user id for agent mode.")
    parser.add_argument("--timeout", type=float, default=180.0, help="HTTP timeout per case in seconds.")
    parser.add_argument("--output", default="", help="Write JSON report to this path.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--no-fail", action="store_true", help="Exit 0 even if cases fail.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
