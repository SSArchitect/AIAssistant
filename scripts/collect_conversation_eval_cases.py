#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.eval.conversation import (  # noqa: E402
    CASE_VERSION,
    build_conversation_eval_candidates,
    utc_now,
)
from agent.config import runtime_config  # noqa: E402


DEFAULT_DB = ROOT / "data" / "assistant.db"
DEFAULT_OUTPUT = ROOT / "evals" / "conversation" / "candidates.json"


def main() -> int:
    args = _parse_args()
    runtime_settings = _runtime_settings_from_db(Path(args.local_db))
    if runtime_settings:
        runtime_config.update(runtime_settings)
    candidates, skipped = build_conversation_eval_candidates(
        args.local_db,
        user_id=args.user_id or None,
        limit=args.limit,
        max_context_messages=args.max_context_messages,
        llm_enabled=args.llm,
        model_preference=args.model_preference or None,
        llm_timeout=args.llm_timeout,
        llm_max_candidates=args.llm_max_candidates,
        scenario_profile=args.scenario_profile,
        quality_profile=args.quality_profile,
        min_quality_score=args.min_quality_score,
    )
    payload = {
        "version": CASE_VERSION,
        "generated_at": utc_now(),
        "description": (
            "Conversation eval candidates mined from real assistant conversations. "
            "Candidates are draft cases; approve and curate them before treating them as regression goldens."
        ),
        "source": {
            "kind": "sqlite",
            "path": str(Path(args.local_db).resolve()),
            "user_id": args.user_id or "",
            "scenario_profile": args.scenario_profile,
            "quality_profile": args.quality_profile,
            "min_quality_score": args.min_quality_score,
            "model_preference": args.model_preference or "",
            "llm_enabled": bool(args.llm),
            "llm_max_candidates": args.llm_max_candidates,
            "runtime_settings_loaded": len(runtime_settings),
        },
        "candidate_count": len(candidates),
        "intent_counts": dict(Counter((item.get("taxonomy") or {}).get("intent") or "unknown" for item in candidates)),
        "priority_counts": dict(Counter((item.get("metadata") or {}).get("priority") or "unknown" for item in candidates)),
        "skipped_counts": skipped,
        "candidates": candidates,
    }
    _write_json(Path(args.output), payload)
    print(
        "Collected conversation eval candidates "
        f"candidates={len(candidates)} skipped={skipped} runtime_settings={len(runtime_settings)} "
        f"output={Path(args.output).resolve()}"
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _runtime_settings_from_db(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'settings'"
        ).fetchone()
        if not row:
            return {}
        settings = conn.execute("select key, value from settings").fetchall()
    finally:
        conn.close()

    result: dict[str, str] = {}
    for key, value in settings:
        normalized_key = str(key or "").strip()
        if not normalized_key.startswith(("llm.", "aigc.", "search.", "mcp.", "tool.")):
            continue
        result[normalized_key] = str(value or "")
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine conversation eval candidates from the assistant SQLite DB.")
    parser.add_argument("--local-db", default=str(DEFAULT_DB), help="Path to assistant SQLite DB.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output candidates JSON path.")
    parser.add_argument("--user-id", default="", help="Optional user id filter.")
    parser.add_argument("--limit", type=int, default=80, help="Maximum candidates to generate; 0 means no limit.")
    parser.add_argument("--max-context-messages", type=int, default=8, help="Max prior messages kept in each case input.")
    parser.add_argument(
        "--scenario-profile",
        choices=["all", "default_qa", "deep_research", "tool_use", "coding"],
        default="all",
        help="Candidate mining profile for scenario-specific eval sets.",
    )
    parser.add_argument(
        "--quality-profile",
        choices=["high_recall", "balanced", "high_precision"],
        default="balanced",
        help="Quality gate for candidate extraction.",
    )
    parser.add_argument("--min-quality-score", type=float, default=None, help="Override the profile quality threshold.")
    parser.add_argument("--llm", action="store_true", help="Use the configured LLM to enrich candidate cases.")
    parser.add_argument("--model-preference", default="", help="Optional provider/model for LLM enrichment.")
    parser.add_argument("--llm-timeout", type=float, default=60.0, help="LLM enrichment timeout per candidate.")
    parser.add_argument("--llm-max-candidates", type=int, default=8, help="Maximum candidates to enrich with LLM.")
    parser.add_argument("--json", action="store_true", help="Print full JSON payload.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
