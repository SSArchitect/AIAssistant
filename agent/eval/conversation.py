from __future__ import annotations

import asyncio
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import sqlite3
import time
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlparse


CASE_VERSION = 2
MAX_CONTEXT_MESSAGES = 8
MAX_MESSAGE_CHARS = 3000
DEFAULT_RUBRIC_PASS_THRESHOLD = 0.75
DEFAULT_RUBRIC_GATES = ["non_empty_response", "no_forbidden_terms", "no_forbidden_tools"]
RUBRIC_SCORE_MIN = 1
RUBRIC_SCORE_MAX = 5
DIMENSION_LABELS = {
    "tool_use": "工具使用",
    "accuracy": "准确性",
    "completeness": "完整性",
    "constraints": "约束遵循",
}
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "you",
    "are",
    "我",
    "你",
    "的",
    "了",
    "是",
    "一下",
    "一个",
    "这个",
    "那个",
    "可以",
    "帮我",
}
CJK_KEY_PHRASES = [
    "电吉他",
    "吉他",
    "指板",
    "柠檬油",
    "保养剂",
    "清洁",
    "护理",
    "轮胎",
    "钢琴",
    "教材",
    "拜厄",
    "车尔尼",
    "哈农",
    "网盘",
    "报告",
    "图片",
    "模型",
    "用例",
    "评测",
]
CJK_CHUNK_PREFIX_STOP = {"我", "你", "帮", "请", "想", "要", "这", "那", "可", "需", "在", "有", "给", "把"}
SCENARIO_PROFILES = {"all", "default_qa", "deep_research", "tool_use", "coding"}
QUALITY_PROFILES = {
    "high_recall": 0.35,
    "balanced": 0.55,
    "high_precision": 0.68,
}


class ConversationEvalError(ValueError):
    """Raised when conversation eval input is malformed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_conversation_eval_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ConversationEvalError("conversation eval payload must contain a cases list")
    normalized: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ConversationEvalError(f"case #{index} must be an object")
        case_id = clean_text(case.get("id"))
        messages = (((case.get("input") or {}).get("messages")) or [])
        if not case_id:
            raise ConversationEvalError(f"case #{index} missing id")
        if not isinstance(messages, list) or not messages:
            raise ConversationEvalError(f"case {case_id} missing input.messages")
        normalized.append(case)
    return normalized


def build_conversation_eval_candidates(
    db_path: str | Path,
    *,
    user_id: str | None = None,
    limit: int = 80,
    max_context_messages: int = MAX_CONTEXT_MESSAGES,
    llm_enabled: bool = False,
    model_preference: str | None = None,
    llm_timeout: float = 20.0,
    llm_max_candidates: int = 24,
    scenario_profile: str = "all",
    quality_profile: str = "balanced",
    min_quality_score: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    db_path = Path(db_path)
    if not db_path.exists():
        raise ConversationEvalError(f"database not found: {db_path}")

    scenario_profile = _normalized_scenario_profile(scenario_profile)
    quality_profile = _normalized_quality_profile(quality_profile)
    quality_threshold = _quality_threshold(quality_profile, min_quality_score)
    conversations = _load_conversation_messages(db_path, user_id=user_id)
    candidates_by_key: dict[str, dict[str, Any]] = {}
    skipped: Counter[str] = Counter()
    llm_enricher: _LLMCaseEnricher | None = None
    llm_init_error = ""
    llm_remaining = max(0, llm_max_candidates)
    if llm_enabled and llm_remaining:
        try:
            llm_enricher = _LLMCaseEnricher(model_preference=model_preference, timeout_seconds=llm_timeout)
        except Exception as exc:  # pragma: no cover - depends on local provider config
            llm_init_error = str(exc)

    for conversation in conversations:
        messages = conversation["messages"]
        for assistant_index, assistant in enumerate(messages):
            if assistant.get("role") != "assistant":
                continue
            user_index = _previous_user_index(messages, assistant_index)
            if user_index is None:
                skipped["missing_user_turn"] += 1
                continue
            user_message = messages[user_index]
            user_text = clean_text(user_message.get("content"))
            assistant_text = clean_text(assistant.get("content"))
            if not _meaningful_user_text(user_text):
                skipped["low_signal_user_turn"] += 1
                continue
            if not assistant_text and not clean_text(assistant.get("error_type")):
                skipped["empty_assistant_turn"] += 1
                continue

            candidate = _candidate_from_turn(
                conversation,
                messages,
                user_index=user_index,
                assistant_index=assistant_index,
                max_context_messages=max_context_messages,
            )
            if not _candidate_matches_scenario_profile(
                candidate,
                scenario_profile=scenario_profile,
                user_text=user_text,
                assistant_text=assistant_text,
            ):
                skipped[f"scenario_profile:{scenario_profile}"] += 1
                continue
            candidate["metadata"]["scenario_profile"] = scenario_profile
            candidate["metadata"]["quality_profile"] = quality_profile
            score, reasons = _candidate_quality(candidate, user_text=user_text, assistant_text=assistant_text)
            candidate["metadata"]["candidate_quality_score"] = score
            candidate["metadata"]["candidate_quality_reasons"] = reasons
            if score < quality_threshold:
                skipped[f"quality_below:{quality_profile}"] += 1
                continue
            key = candidate["metadata"]["dedupe_key"]
            existing = candidates_by_key.get(key)
            if existing:
                skipped["duplicate"] += 1
                if _candidate_sort_key(candidate) > _candidate_sort_key(existing):
                    candidates_by_key[key] = candidate
                continue
            candidates_by_key[key] = candidate

    candidates = sorted(candidates_by_key.values(), key=_candidate_sort_key, reverse=True)
    enriched_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        user_message, assistant_message, conversation = _candidate_source_turn(candidate, conversations)
        if llm_enabled:
            if llm_enricher and llm_remaining > 0 and user_message and assistant_message and conversation:
                candidate = _enrich_candidate_with_llm(
                    candidate,
                    conversation=conversation,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    enricher=llm_enricher,
                )
                llm_remaining -= 1
            else:
                _mark_llm_enrichment(
                    candidate,
                    status="skipped",
                    reason=llm_init_error or "llm_max_candidates_reached",
                )
        if _candidate_rejected_after_llm(candidate, quality_threshold=quality_threshold):
            skipped["llm_rejected"] += 1
            continue
        enriched_candidates.append(candidate)

    enriched_candidates = sorted(enriched_candidates, key=_candidate_sort_key, reverse=True)
    if limit > 0:
        enriched_candidates = enriched_candidates[:limit]
    return enriched_candidates, dict(skipped)


def _normalized_quality_profile(value: str) -> str:
    normalized = clean_text(value).lower().replace("-", "_")
    return normalized if normalized in QUALITY_PROFILES else "balanced"


def _quality_threshold(profile: str, override: float | None) -> float:
    if override is not None:
        return _clamp01(override)
    return QUALITY_PROFILES.get(profile, QUALITY_PROFILES["balanced"])


def _candidate_quality(
    candidate: dict[str, Any],
    *,
    user_text: str,
    assistant_text: str,
) -> tuple[float, list[str]]:
    taxonomy = candidate.get("taxonomy") if isinstance(candidate.get("taxonomy"), dict) else {}
    expected = candidate.get("expected") if isinstance(candidate.get("expected"), dict) else {}
    historical = candidate.get("historical_response") if isinstance(candidate.get("historical_response"), dict) else {}
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    intent = clean_text(taxonomy.get("intent"))
    edge_cases = _string_list(taxonomy.get("edge_cases"))
    failure_modes = _string_list(taxonomy.get("failure_modes"))
    required_tools = _string_list(((expected.get("tools") or {}).get("required")) if isinstance(expected.get("tools"), dict) else [])
    answer_result = _string_list(((expected.get("include") or {}).get("answer_result")) if isinstance(expected.get("include"), dict) else [])
    skills_used = _string_list(historical.get("skills_used"))
    citations = _list_of_dicts(historical.get("citations"))
    score = 0.18
    reasons: list[str] = []

    if len(user_text) >= 12:
        score += 0.10
        reasons.append("clear_user_goal")
    if len(assistant_text) >= 60:
        score += 0.08
        reasons.append("substantive_historical_answer")
    if intent and intent != "general_qa":
        score += 0.12
        reasons.append(f"intent:{intent}")
    if required_tools or skills_used:
        score += 0.12
        reasons.append("tool_signal")
    if citations:
        score += 0.06
        reasons.append("citation_signal")
    if edge_cases:
        score += min(0.12, 0.04 * len(edge_cases))
        reasons.append("edge_case")
    if failure_modes:
        score += min(0.22, 0.10 * len(failure_modes))
        reasons.append("failure_or_regression_risk")
    if answer_result:
        score += min(0.10, 0.025 * len(answer_result))
        reasons.append("observable_expected_result")
    if metadata.get("priority") == "p1":
        score += 0.08
        reasons.append("p1_priority")
    if _has_actionable_task_signal(user_text):
        score += 0.08
        reasons.append("actionable_task")
    if _is_low_value_eval_turn(user_text, assistant_text):
        score -= 0.22
        reasons.append("low_value_turn")
    return round(_clamp01(score), 3), _dedupe_preserve(reasons)[:8]


def _has_actionable_task_signal(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"\b(compare|search|find|build|write|debug|explain|summarize|research|generate)\b", lowered)
        or any(
            term in text
            for term in (
                "帮我",
                "查",
                "搜索",
                "对比",
                "分析",
                "总结",
                "生成",
                "实现",
                "修复",
                "解释",
                "推荐",
                "整理",
                "评测",
                "回归",
            )
        )
    )


def _is_low_value_eval_turn(user_text: str, assistant_text: str) -> bool:
    lowered = user_text.lower().strip()
    low_value_exact = {
        "继续",
        "可以",
        "好的",
        "嗯",
        "好",
        "ok",
        "yes",
        "go on",
        "继续吧",
        "没了",
    }
    if lowered in low_value_exact:
        return True
    if len(user_text) < 8 and not re.search(r"https?://|[A-Za-z]+[^A-Za-z0-9]{0,4}\d+|\d+[^A-Za-z0-9]{0,4}[A-Za-z]+", user_text):
        return True
    if len(assistant_text) < 24 and not any(term in user_text for term in ("报错", "错误", "失败", "不能", "无法")):
        return True
    return False


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, float, float, str]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    taxonomy = candidate.get("taxonomy") if isinstance(candidate.get("taxonomy"), dict) else {}
    priority_rank = {"p1": 3.0, "p2": 2.0, "p3": 1.0}.get(clean_text(metadata.get("priority")), 0.0)
    quality = _float_or_none(metadata.get("candidate_quality_score"))
    if quality is None:
        quality = _float_or_none(metadata.get("auto_confidence")) or 0.0
    risk = len(_string_list(taxonomy.get("failure_modes"))) * 0.1 + len(_string_list(taxonomy.get("edge_cases"))) * 0.03
    created = clean_text((candidate.get("source") or {}).get("created_at") if isinstance(candidate.get("source"), dict) else "")
    return (priority_rank, quality, risk, created)


def _candidate_rejected_after_llm(candidate: dict[str, Any], *, quality_threshold: float) -> bool:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    decision = metadata.get("candidate_decision") if isinstance(metadata.get("candidate_decision"), dict) else {}
    if decision.get("keep") is False:
        return True
    llm_quality = _float_or_none(decision.get("quality_score"))
    if llm_quality is not None and llm_quality < quality_threshold:
        return True
    return False


def _candidate_source_turn(
    candidate: dict[str, Any],
    conversations: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    conversation_id = clean_text(source.get("conversation_id"))
    message_ids = source.get("message_ids") if isinstance(source.get("message_ids"), list) else []
    if len(message_ids) < 2:
        return None, None, None
    user_id, assistant_id = int(message_ids[0] or 0), int(message_ids[1] or 0)
    for conversation in conversations:
        if clean_text(conversation.get("id")) != conversation_id:
            continue
        messages = conversation.get("messages") if isinstance(conversation.get("messages"), list) else []
        user_message = next((item for item in messages if int(item.get("id") or 0) == user_id), None)
        assistant_message = next((item for item in messages if int(item.get("id") or 0) == assistant_id), None)
        return user_message, assistant_message, conversation
    return None, None, None


class _LLMCaseEnricher:
    def __init__(self, *, model_preference: str | None, timeout_seconds: float):
        from agent.llm.factory import create_provider

        self.provider = create_provider(model_preference)
        self.timeout_seconds = max(1.0, float(timeout_seconds or 20.0))

    def enrich(
        self,
        *,
        candidate: dict[str, Any],
        conversation: dict[str, Any],
        user_message: dict[str, Any],
        assistant_message: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self._async_enrich(
                    candidate=candidate,
                    conversation=conversation,
                    user_message=user_message,
                    assistant_message=assistant_message,
                )
            )
        raise RuntimeError("LLM enrichment cannot run inside an active event loop")

    async def _async_enrich(
        self,
        *,
        candidate: dict[str, Any],
        conversation: dict[str, Any],
        user_message: dict[str, Any],
        assistant_message: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from agent.llm.base import LLMMessage

        payload = {
            "conversation_title": clean_text(conversation.get("title")),
            "user_message": clean_text(user_message.get("content"))[:MAX_MESSAGE_CHARS],
            "assistant_response": clean_text(assistant_message.get("content"))[:MAX_MESSAGE_CHARS],
            "skills_used": _string_list(assistant_message.get("skills_used")),
            "citations": _list_of_dicts(assistant_message.get("citations"))[:6],
            "artifacts": _list_of_dicts(assistant_message.get("artifacts"))[:4],
            "trace_summary": _list_of_dicts(assistant_message.get("trace_summary"))[:8],
            "current_candidate": {
                "scenario": (candidate.get("taxonomy") or {}).get("scenario") or "",
                "intent": (candidate.get("taxonomy") or {}).get("intent") or "",
                "edge_cases": (candidate.get("taxonomy") or {}).get("edge_cases") or [],
                "failure_modes": (candidate.get("taxonomy") or {}).get("failure_modes") or [],
                "expected": candidate.get("expected") or {},
                "metadata": candidate.get("metadata") or {},
            },
        }
        response = await asyncio.wait_for(
            self.provider.chat(
                [
                    LLMMessage(
                        role="system",
                        content=(
                            "你是 Conversation Eval 用例挖掘器。根据真实用户消息、助手历史回答、工具调用和 trace，"
                            "把候选用例整理成可人工审核、可训练、可评测、可回归的结构化用例。"
                            "你必须先判断这条候选是否值得进入候选集：只保留目标明确、可观察评分、能覆盖真实风险或关键能力的用例；"
                            "拒绝寒暄、确认、重复追问、缺少明确任务、只能靠人工猜测标准、或历史回答没有可评测结果的候选。"
                            "不要输出模型内部思考链，不要编造不存在的工具调用。"
                            "场景要是短标题，能让人一眼知道这个 case 在测什么；"
                            "答案结果要写成期望最终回答应覆盖的可观察事实/结论，不要只是机械切词。"
                            "评分维度需要给出标准、标准要求和 1-5 通过分。只返回严格 JSON。"
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            "输入 JSON：\n"
                            f"{json.dumps(payload, ensure_ascii=False)}\n\n"
                            "请返回这个精确结构，字段可为空数组但不能省略：\n"
                            "{"
                            '"decision":{"keep":true,"quality_score":0.0,"reason":"保留或拒绝原因","review_notes":["..."]},'
                            '"scenario":"短场景标题",'
                            '"intent":"information_lookup|url_understanding|image_generation|artifact_generation|coding_or_debugging|content_transformation|general_qa",'
                            '"edge_cases":["..."],'
                            '"failure_modes":["..."],'
                            '"expected":{'
                            '"include":{"tool_calls":["search"],"answer_result":["..."],"citations":["..."]},'
                            '"tools":{"required":["search"],"forbidden":[]},'
                            '"result":{"accuracy":{"must_include":["..."],"min_must_include":1,"must_not_include":["..."]},'
                            '"completeness":{"required_points":[{"label":"...","any_text_contains":["..."]}],"min_required_points":1,"min_score":0.6}}'
                            "},"
                            '"rubric":{"dimensions":[{"id":"tool_use","standard":"...","requirements":["..."],"passing_score":4},'
                            '{"id":"accuracy","standard":"...","requirements":["..."],"passing_score":4},'
                            '{"id":"completeness","standard":"...","requirements":["..."],"passing_score":4},'
                            '{"id":"constraints","standard":"...","requirements":["..."],"passing_score":5}]},'
                            '"metadata":{"priority":"p1|p2|p3","tags":["..."],"auto_confidence":0.0}'
                            "}"
                            "\n如果 decision.keep=false，仍返回完整结构，但其他字段可以沿用输入候选。"
                        ),
                    ),
                ],
                tools=None,
                temperature=0.2,
            ),
            timeout=self.timeout_seconds,
        )
        parsed = _json_object_from_text(response.content)
        if not parsed:
            raise ValueError("LLM enrichment returned no JSON object")
        return parsed, {"model": response.model, "usage": response.usage}


def _enrich_candidate_with_llm(
    candidate: dict[str, Any],
    *,
    conversation: dict[str, Any],
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    enricher: _LLMCaseEnricher,
) -> dict[str, Any]:
    last_reason = ""
    attempts_used = 0
    for attempt in range(1, 3):
        attempts_used = attempt
        try:
            payload, response_meta = enricher.enrich(
                candidate=candidate,
                conversation=conversation,
                user_message=user_message,
                assistant_message=assistant_message,
            )
            _apply_llm_candidate_payload(candidate, payload)
            _mark_llm_enrichment(
                candidate,
                status="completed",
                model=clean_text(response_meta.get("model")),
                usage=response_meta.get("usage") if isinstance(response_meta.get("usage"), dict) else {},
                attempts=attempt,
            )
            return candidate
        except Exception as exc:  # pragma: no cover - provider/network dependent
            reason = clean_text(str(exc)) or exc.__class__.__name__
            last_reason = reason[:240]
            if not _retryable_llm_enrichment_error(reason) or attempt >= 2:
                break
            time.sleep(0.75 * attempt)
    _mark_llm_enrichment(candidate, status="failed", reason=last_reason, attempts=attempts_used)
    return candidate


def _retryable_llm_enrichment_error(reason: str) -> bool:
    lowered = clean_text(reason).lower()
    return not lowered or any(
        term in lowered
        for term in (
            "connection error",
            "timeout",
            "timed out",
            "temporarily",
            "remote protocol",
            "server disconnected",
        )
    )


def _apply_llm_candidate_payload(candidate: dict[str, Any], payload: dict[str, Any]) -> None:
    taxonomy = candidate.setdefault("taxonomy", {})
    scenario = clean_text(payload.get("scenario"))
    if scenario:
        taxonomy["scenario"] = scenario[:120]
    intent = clean_text(payload.get("intent"))
    if intent:
        taxonomy["intent"] = intent
    edge_cases = _string_list(payload.get("edge_cases"))
    if edge_cases:
        taxonomy["edge_cases"] = edge_cases[:12]
    failure_modes = _string_list(payload.get("failure_modes"))
    if failure_modes:
        taxonomy["failure_modes"] = failure_modes[:12]

    expected = candidate.setdefault("expected", {})
    _apply_llm_expected(expected, payload.get("expected"))
    expected_normalized = _normalized_expected(expected)
    candidate["expected"] = _denormalized_expected_for_case(expected, expected_normalized)
    candidate["rubric"] = _rubric_with_llm_overrides(
        _default_rubric(candidate["expected"], pass_threshold=DEFAULT_RUBRIC_PASS_THRESHOLD),
        payload.get("rubric"),
    )

    metadata_payload = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata = candidate.setdefault("metadata", {})
    decision_payload = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    if decision_payload:
        keep_raw = decision_payload.get("keep")
        quality_score = _float_or_none(decision_payload.get("quality_score"))
        metadata["candidate_decision"] = {
            "keep": bool(keep_raw) if isinstance(keep_raw, bool) else True,
            "quality_score": _clamp01(quality_score) if quality_score is not None else metadata.get("candidate_quality_score"),
            "reason": clean_text(decision_payload.get("reason"))[:240],
            "review_notes": _string_list(decision_payload.get("review_notes"))[:6],
        }
        if quality_score is not None:
            metadata["candidate_quality_score"] = _clamp01(quality_score)
    priority = clean_text(metadata_payload.get("priority"))
    if priority in {"p1", "p2", "p3"}:
        metadata["priority"] = priority
    tags = _string_list(metadata_payload.get("tags"))
    if tags:
        metadata["tags"] = tags[:12]
    confidence = _float_or_none(metadata_payload.get("auto_confidence"))
    if confidence is not None:
        metadata["auto_confidence"] = _clamp01(confidence)
    candidate["scoring"] = {
        **(candidate.get("scoring") if isinstance(candidate.get("scoring"), dict) else {}),
        "judge_prompt": "llm_enriched_candidate_v1",
    }


def _apply_llm_expected(expected: dict[str, Any], raw: Any) -> None:
    if not isinstance(raw, dict):
        return
    include = expected.setdefault("include", {})
    raw_include = raw.get("include") if isinstance(raw.get("include"), dict) else {}
    answer_result = _string_list(raw_include.get("answer_result"))
    tool_calls = _string_list(raw_include.get("tool_calls"))
    citations = _string_list(raw_include.get("citations"))
    if answer_result and _should_replace_answer_result(_string_list(include.get("answer_result")), answer_result):
        include["answer_result"] = answer_result[:8]
    if tool_calls:
        include["tool_calls"] = tool_calls[:6]
    if citations:
        include["citations"] = citations[:6]

    raw_tools = raw.get("tools") if isinstance(raw.get("tools"), dict) else {}
    tools = expected.setdefault("tools", {})
    required = _dedupe_preserve([*_string_list(raw_tools.get("required")), *_string_list(include.get("tool_calls"))])
    if required:
        tools["required"] = required[:6]
        include["tool_calls"] = required[:6]
    forbidden_tools = _string_list(raw_tools.get("forbidden"))
    if forbidden_tools:
        tools["forbidden"] = forbidden_tools[:6]

    raw_result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    raw_accuracy = raw_result.get("accuracy") if isinstance(raw_result.get("accuracy"), dict) else {}
    raw_completeness = raw_result.get("completeness") if isinstance(raw_result.get("completeness"), dict) else {}
    result = expected.setdefault("result", {})
    accuracy = result.setdefault("accuracy", {})
    must_include = _string_list(raw_accuracy.get("must_include")) or _string_list(include.get("answer_result"))
    if must_include:
        accuracy["must_include"] = must_include[:8]
        if _should_replace_answer_result(_string_list(include.get("answer_result")), must_include):
            include["answer_result"] = must_include[:8]
    must_not_include = _string_list(raw_accuracy.get("must_not_include"))
    if must_not_include:
        accuracy["must_not_include"] = must_not_include[:8]
    min_must_include = _positive_int(raw_accuracy.get("min_must_include"), default=0)
    if min_must_include:
        accuracy["min_must_include"] = min(min_must_include, len(_string_list(accuracy.get("must_include"))))

    completeness = result.setdefault("completeness", {})
    points = _normalized_completeness_points(raw_completeness.get("required_points"))
    if points:
        completeness["required_points"] = points[:8]
    min_required = _positive_int(raw_completeness.get("min_required_points"), default=0)
    if min_required:
        completeness["min_required_points"] = min(min_required, len(_normalized_completeness_points(completeness.get("required_points"))))
    min_score = _float_or_none(raw_completeness.get("min_score"))
    if min_score is not None:
        completeness["min_score"] = _clamp01(min_score)


def _should_replace_answer_result(existing: list[str], incoming: list[str]) -> bool:
    incoming = _string_list(incoming)
    if not incoming:
        return False
    existing = _string_list(existing)
    if not existing:
        return True
    return _answer_result_detail_score(incoming) >= _answer_result_detail_score(existing)


def _answer_result_detail_score(values: list[str]) -> int:
    score = 0
    for value in _string_list(values):
        text = clean_text(value)
        if len(text) >= 36:
            score += 4
        elif len(text) >= 16:
            score += 2
        elif len(text) >= 6:
            score += 1
        if any(mark in text for mark in ("：", ":", "；", ";", "（", "(", "/", "、")):
            score += 1
        if re.search(r"\b(?:No\.\s*\d+|Formula|[A-Za-z]+\d|\d+[A-Za-z]|20\d{2})\b|\.md\b", text):
            score += 1
    return score


def _denormalized_expected_for_case(original: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    include = normalized["include"]
    accuracy = normalized["result"]["accuracy"]
    completeness = normalized["result"]["completeness"]
    expected = {
        **original,
        "include": include,
        "tools": normalized["tools"],
        "result": normalized["result"],
        "must_include": _string_list(accuracy.get("must_include")),
        "min_must_include": _positive_int(
            accuracy.get("min_must_include"),
            default=min(len(_string_list(accuracy.get("must_include"))), 2),
        ),
        "must_not_include": _string_list(accuracy.get("must_not_include")),
        "tool_expectations": [{"name": name, "required": True} for name in _string_list(normalized["tools"].get("required"))],
    }
    if not completeness.get("required_points") and include.get("answer_result"):
        expected["result"]["completeness"] = {
            **completeness,
            "required_points": [
                {"label": f"answer_result_{index}", "any_text_contains": [text]}
                for index, text in enumerate(_string_list(include.get("answer_result")), start=1)
            ],
        }
    return expected


def _rubric_with_llm_overrides(rubric: dict[str, Any], raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return rubric
    raw_dimensions = raw.get("dimensions")
    if not isinstance(raw_dimensions, list):
        return rubric
    overrides: dict[str, dict[str, Any]] = {}
    for item in raw_dimensions:
        if not isinstance(item, dict):
            continue
        dimension_id = clean_text(item.get("id"))
        if dimension_id:
            overrides[dimension_id] = item
    for dimension in rubric.get("dimensions") or []:
        override = overrides.get(clean_text(dimension.get("id")))
        if not override:
            continue
        standard = clean_text(override.get("standard"))
        requirements = _string_list(override.get("requirements"))
        passing_score = _positive_int(override.get("passing_score"), default=0)
        if standard:
            dimension["standard"] = standard
        if requirements:
            dimension["requirements"] = requirements[:8]
        if passing_score:
            dimension["passing_score"] = _clamp_rating(passing_score)
            dimension["threshold"] = _rating_to_threshold(dimension["passing_score"])
    rubric["pass_threshold"] = _implied_pass_threshold(rubric.get("dimensions") or [])
    return rubric


def _mark_llm_enrichment(candidate: dict[str, Any], *, status: str, **extra: Any) -> None:
    metadata = candidate.setdefault("metadata", {})
    metadata["llm_enrichment"] = {
        "status": status,
        **{key: value for key, value in extra.items() if value not in (None, "", {})},
    }


def _json_object_from_text(text: str) -> dict[str, Any]:
    value = (text or "").strip()
    if not value:
        return {}
    if value.startswith("```"):
        value = value.strip("`").strip()
        if value.lower().startswith("json"):
            value = value[4:].strip()
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(value[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def evaluate_conversation_case(
    case: dict[str, Any],
    *,
    response_text: str | None = None,
    skills_used: list[str] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    expected = _normalized_expected(case.get("expected"))
    historical = case.get("historical_response") if isinstance(case.get("historical_response"), dict) else {}
    response_text = clean_text(response_text if response_text is not None else historical.get("content"))
    skills_used = skills_used if skills_used is not None else _string_list(historical.get("skills_used"))
    events = events if events is not None else _list_of_dicts(historical.get("trace_summary"))

    tools_expected = expected["tools"]
    accuracy_expected = expected["result"]["accuracy"]
    completeness_expected = expected["result"]["completeness"]
    must_include = _string_list(accuracy_expected.get("must_include"))
    must_not_include = _string_list(accuracy_expected.get("must_not_include"))
    min_must_include = _positive_int(
        accuracy_expected.get("min_must_include"),
        default=min(len(must_include), 2) if must_include else 0,
    )
    missing_terms = [term for term in must_include if not _contains(response_text, term)]
    forbidden_terms = [term for term in must_not_include if _contains(response_text, term)]
    included_count = len(must_include) - len(missing_terms)

    required_tools = _string_list(tools_expected.get("required"))
    forbidden_tools = _string_list(tools_expected.get("forbidden"))
    missing_tools = [tool for tool in required_tools if not _tool_used(tool, skills_used, events)]
    unexpected_tools = [tool for tool in forbidden_tools if _tool_used(tool, skills_used, events)]
    points = _normalized_completeness_points(completeness_expected.get("required_points"))
    matched_points, missing_points = _score_completeness_points(response_text, points)
    completeness_score = 1.0 if not points else len(matched_points) / len(points)
    min_completeness_score = _float_or_none(completeness_expected.get("min_score"))
    if min_completeness_score is None:
        min_completeness_score = 0.0 if not points else 0.6
    min_required_points = _positive_int(
        completeness_expected.get("min_required_points"),
        default=0,
    )

    failures: list[str] = []
    if min_must_include and included_count < min_must_include:
        failures.append(
            f"must_include matched {included_count}/{len(must_include)} < {min_must_include}: "
            + ", ".join(missing_terms[:5])
        )
    if forbidden_terms:
        failures.append("forbidden terms present: " + ", ".join(forbidden_terms[:5]))
    if missing_tools:
        failures.append("required tools missing: " + ", ".join(missing_tools))
    if unexpected_tools:
        failures.append("forbidden tools used: " + ", ".join(unexpected_tools))
    if min_required_points and len(matched_points) < min_required_points:
        failures.append(
            f"completeness points matched {len(matched_points)}/{len(points)} < {min_required_points}: "
            + ", ".join(item["label"] for item in missing_points[:5])
        )
    if min_completeness_score and completeness_score < min_completeness_score:
        failures.append(
            f"completeness_score {completeness_score:.3f} < {min_completeness_score:.3f}"
        )
    if not response_text:
        failures.append("response is empty")

    metrics = {
        "must_include_count": len(must_include),
        "must_include_matched": included_count,
        "must_include_ratio": 1.0 if not must_include else included_count / len(must_include),
        "forbidden_present": len(forbidden_terms),
        "required_tool_count": len(required_tools),
        "required_tool_missing": len(missing_tools),
        "forbidden_tool_count": len(forbidden_tools),
        "forbidden_tool_used": len(unexpected_tools),
        "completeness_point_count": len(points),
        "completeness_points_matched": len(matched_points),
        "completeness_score": completeness_score,
        "response_chars": len(response_text),
    }
    matched = {
        "included_terms": [term for term in must_include if term not in missing_terms],
        "missing_terms": missing_terms,
        "forbidden_terms": forbidden_terms,
        "skills_used": skills_used,
        "required_tools": required_tools,
        "missing_tools": missing_tools,
        "forbidden_tools": forbidden_tools,
        "unexpected_tools": unexpected_tools,
        "matched_points": matched_points,
        "missing_points": missing_points,
    }
    rubric = _normalized_rubric(case.get("rubric"), expected)
    scorecard = _score_rubric(
        rubric,
        metrics=metrics,
        matched=matched,
        response_text=response_text,
    )
    if not scorecard["passed"] and not failures:
        failures.append(
            f"scorecard overall_score {scorecard['overall_score']:.3f} < {scorecard['pass_threshold']:.3f}"
        )
    metadata = case.get("metadata") if isinstance(case.get("metadata"), dict) else {}
    return {
        "id": case.get("id") or "",
        "type": case.get("type") or "conversation_task",
        "scenario": ((case.get("taxonomy") or {}).get("scenario")) or "",
        "intent": ((case.get("taxonomy") or {}).get("intent")) or "",
        "tags": _string_list(metadata.get("tags")),
        "priority": clean_text(metadata.get("priority")),
        "passed": not failures,
        "failures": failures,
        "metrics": metrics,
        "scorecard": scorecard,
        "matched": matched,
        "response": {
            "content": response_text[:MAX_MESSAGE_CHARS],
            "skills_used": skills_used,
        },
        "source": case.get("source") or {},
    }


def summarize_conversation_eval(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [item for item in case_results if item.get("passed")]
    failed = [item for item in case_results if not item.get("passed")]
    metrics = [item.get("metrics", {}) for item in case_results]
    scorecards = [item.get("scorecard", {}) for item in case_results if isinstance(item.get("scorecard"), dict)]
    intent_counts: Counter[str] = Counter(str(item.get("intent") or "unknown") for item in case_results)
    return {
        "case_count": len(case_results),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "pass_rate": len(passed) / max(1, len(case_results)),
        "mean_overall_score": _mean_float(item.get("overall_score") for item in scorecards),
        "mean_overall_score_1_5": _mean_float(item.get("overall_score_1_5") for item in scorecards),
        "mean_must_include_ratio": _metric_mean(metrics, "must_include_ratio"),
        "mean_completeness_score": _metric_mean(metrics, "completeness_score"),
        "total_forbidden_present": sum(int(item.get("forbidden_present") or 0) for item in metrics),
        "total_required_tool_missing": sum(int(item.get("required_tool_missing") or 0) for item in metrics),
        "total_forbidden_tool_used": sum(int(item.get("forbidden_tool_used") or 0) for item in metrics),
        "dimension_scores": _summarize_dimensions(case_results),
        "tag_slices": _summarize_tag_slices(case_results),
        "intent_counts": dict(intent_counts),
        "failed_cases": [str(item.get("id")) for item in failed],
    }


def _normalized_expected(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    include = source.get("include") if isinstance(source.get("include"), dict) else {}
    tools = source.get("tools") if isinstance(source.get("tools"), dict) else {}
    result = source.get("result") if isinstance(source.get("result"), dict) else {}
    accuracy = result.get("accuracy") if isinstance(result.get("accuracy"), dict) else {}
    completeness = result.get("completeness") if isinstance(result.get("completeness"), dict) else {}

    include_tool_calls = _string_list(include.get("tool_calls"))
    include_answer_result = _string_list(include.get("answer_result"))
    include_citations = _string_list(include.get("citations"))
    explicit_must_include = _dedupe_preserve(
        [*_string_list(accuracy.get("must_include")), *_string_list(source.get("must_include"))]
    )
    legacy_required_tools = [
        clean_text(item.get("name"))
        for item in (source.get("tool_expectations") or [])
        if isinstance(item, dict) and item.get("required") and clean_text(item.get("name"))
    ]
    return {
        "behavior": clean_text(source.get("behavior")),
        "include": {
            "tool_calls": include_tool_calls,
            "answer_result": include_answer_result,
            "citations": include_citations,
        },
        "tools": {
            "required": _dedupe_preserve(
                [*_string_list(tools.get("required")), *include_tool_calls, *legacy_required_tools]
            ),
            "optional": _string_list(tools.get("optional")),
            "forbidden": _string_list(tools.get("forbidden")),
        },
        "result": {
            "accuracy": {
                "must_include": explicit_must_include or include_answer_result,
                "min_must_include": accuracy.get("min_must_include", source.get("min_must_include")),
                "must_not_include": _dedupe_preserve(
                    [*_string_list(accuracy.get("must_not_include")), *_string_list(source.get("must_not_include"))]
                ),
            },
            "completeness": {
                "required_points": completeness.get("required_points") or [],
                "min_required_points": completeness.get("min_required_points", 0),
                "min_score": completeness.get("min_score", 0.0),
            },
        },
    }


def _default_rubric(
    expected: dict[str, Any],
    *,
    pass_threshold: float | None = None,
) -> dict[str, Any]:
    dimensions = _default_rubric_dimensions(expected)
    threshold = pass_threshold if pass_threshold is not None else _implied_pass_threshold(dimensions)
    return {
        "schema_version": 2,
        "pass_threshold": _clamp01(threshold),
        "gates": list(DEFAULT_RUBRIC_GATES),
        "dimensions": dimensions,
    }


def _normalized_rubric(value: Any, expected: dict[str, Any]) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    dimensions = _normalized_rubric_dimensions(source.get("dimensions"), expected)
    if not dimensions:
        dimensions = _default_rubric_dimensions(expected)
    pass_threshold = _float_or_none(source.get("pass_threshold"))
    if pass_threshold is None:
        pass_threshold = _implied_pass_threshold(dimensions)
    gates = _string_list(source.get("gates")) or list(DEFAULT_RUBRIC_GATES)
    return {
        "schema_version": _positive_int(source.get("schema_version"), default=2),
        "pass_threshold": _clamp01(pass_threshold),
        "gates": gates,
        "dimensions": dimensions,
    }


def _normalized_rubric_dimensions(value: Any, expected: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    defaults = {item["id"]: item for item in _default_rubric_dimensions(expected)}
    dimensions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        dimension_id = clean_text(raw.get("id"))
        if not dimension_id or dimension_id in seen:
            continue
        seen.add(dimension_id)
        default = defaults.get(
            dimension_id,
            {
                "id": dimension_id,
                "label": dimension_id,
                "threshold": 0.0,
                "passing_score": RUBRIC_SCORE_MIN,
                "scorer": "manual",
                "checks": {},
                "standard": "",
                "requirements": [],
            },
        )
        standard_dimension = dimension_id in defaults
        checks = default.get("checks", {}) if standard_dimension else (
            raw.get("checks") if isinstance(raw.get("checks"), dict) else default.get("checks", {})
        )
        threshold = _float_or_none(raw.get("threshold"))
        passing_score = _rubric_passing_score(raw.get("passing_score"), threshold, default)
        threshold = _rubric_threshold(threshold, passing_score, default)
        if standard_dimension:
            default_threshold = _clamp01(default.get("threshold"))
            threshold = max(threshold, default_threshold)
            passing_score = max(passing_score, _threshold_to_rating(default_threshold))
        dimensions.append(
            {
                "id": dimension_id,
                "label": clean_text(raw.get("label")) or default.get("label") or dimension_id,
                "standard": clean_text(raw.get("standard")) or default.get("standard") or "",
                "requirements": _string_list(raw.get("requirements")) or _string_list(default.get("requirements")),
                "passing_score": passing_score,
                "score_scale": {"min": RUBRIC_SCORE_MIN, "max": RUBRIC_SCORE_MAX},
                "threshold": threshold,
                "scorer": clean_text(raw.get("scorer")) or default.get("scorer") or "deterministic",
                "checks": checks,
            }
        )
    return dimensions


def _default_rubric_dimensions(expected: dict[str, Any]) -> list[dict[str, Any]]:
    tools = expected["tools"]
    accuracy = expected["result"]["accuracy"]
    completeness = expected["result"]["completeness"]
    dimensions = [
        {
            "id": "tool_use",
            "label": DIMENSION_LABELS["tool_use"],
            "threshold": _tool_use_threshold(tools),
            "standard": _dimension_standard("tool_use"),
            "requirements": _dimension_requirements("tool_use", expected),
            "scorer": "trace_assertion",
            "checks": {
                "required_tools": _string_list(tools.get("required")),
                "forbidden_tools": _string_list(tools.get("forbidden")),
            },
        },
        {
            "id": "accuracy",
            "label": DIMENSION_LABELS["accuracy"],
            "threshold": _accuracy_threshold(accuracy),
            "standard": _dimension_standard("accuracy"),
            "requirements": _dimension_requirements("accuracy", expected),
            "scorer": "keyword_coverage",
            "checks": {
                "must_include": _string_list(accuracy.get("must_include")),
                "min_must_include": accuracy.get("min_must_include"),
                "must_not_include": _string_list(accuracy.get("must_not_include")),
            },
        },
        {
            "id": "completeness",
            "label": DIMENSION_LABELS["completeness"],
            "threshold": _completeness_threshold(completeness),
            "standard": _dimension_standard("completeness"),
            "requirements": _dimension_requirements("completeness", expected),
            "scorer": "point_coverage",
            "checks": {
                "required_points": _normalized_completeness_points(completeness.get("required_points")),
                "min_required_points": completeness.get("min_required_points"),
                "min_score": completeness.get("min_score"),
            },
        },
        {
            "id": "constraints",
            "label": DIMENSION_LABELS["constraints"],
            "threshold": 1.0,
            "standard": _dimension_standard("constraints"),
            "requirements": _dimension_requirements("constraints", expected),
            "scorer": "hard_gates",
            "checks": {
                "non_empty_response": True,
                "no_forbidden_terms": True,
                "no_forbidden_tools": True,
            },
        },
    ]
    for dimension in dimensions:
        dimension["passing_score"] = _threshold_to_rating(dimension.get("threshold"))
        dimension["score_scale"] = {"min": RUBRIC_SCORE_MIN, "max": RUBRIC_SCORE_MAX}
    return dimensions


def _dimension_standard(dimension_id: str) -> str:
    if dimension_id == "tool_use":
        return "按用例要求调用必要工具，并避免调用禁用工具。"
    if dimension_id == "accuracy":
        return "答案结果覆盖应包含信息，且不出现禁用内容或明显偏题内容。"
    if dimension_id == "completeness":
        return "回答覆盖关键结果点，必要时说明步骤、限制、上下文和取舍。"
    if dimension_id == "constraints":
        return "响应非空，并遵守禁用词、禁用工具和基础安全约束。"
    return "按该维度的标准要求完成任务。"


def _dimension_requirements(dimension_id: str, expected: dict[str, Any]) -> list[str]:
    tools = expected["tools"]
    accuracy = expected["result"]["accuracy"]
    completeness = expected["result"]["completeness"]
    if dimension_id == "tool_use":
        requirements = []
        required_tools = _string_list(tools.get("required"))
        forbidden_tools = _string_list(tools.get("forbidden"))
        if required_tools:
            requirements.append("必须调用工具：" + "、".join(required_tools))
        if forbidden_tools:
            requirements.append("不得调用工具：" + "、".join(forbidden_tools))
        return requirements or ["无强制工具要求时，不因无工具调用扣分。"]
    if dimension_id == "accuracy":
        requirements = [f"答案应包含：{item}" for item in _string_list(accuracy.get("must_include"))]
        requirements.extend(f"答案不得包含：{item}" for item in _string_list(accuracy.get("must_not_include")))
        return requirements or ["答案应直接回应用户问题，避免臆造未给出的事实。"]
    if dimension_id == "completeness":
        points = _normalized_completeness_points(completeness.get("required_points"))
        requirements = [f"覆盖要点：{clean_text(point.get('label'))}" for point in points if clean_text(point.get("label"))]
        min_required = _positive_int(completeness.get("min_required_points"), default=0)
        min_score = _float_or_none(completeness.get("min_score"))
        if min_required:
            requirements.append(f"至少覆盖 {min_required} 个完整性要点。")
        if min_score is not None and min_score > 0:
            requirements.append(f"完整性命中率不低于 {min_score:.2f}。")
        return requirements or ["覆盖用户请求中的主要任务，不遗漏关键限制或输出要求。"]
    if dimension_id == "constraints":
        return ["响应不能为空。", "不得出现禁用词。", "不得调用禁用工具。"]
    return []


def _rubric_passing_score(value: Any, threshold: float | None, default: dict[str, Any]) -> int:
    parsed = _positive_int(value, default=0)
    if parsed:
        return _clamp_rating(parsed)
    default_score = _positive_int(default.get("passing_score"), default=0)
    if default_score:
        return _clamp_rating(default_score)
    if threshold is not None:
        return _threshold_to_rating(threshold)
    return _threshold_to_rating(default.get("threshold"))


def _rubric_threshold(value: float | None, passing_score: int, default: dict[str, Any]) -> float:
    if value is not None:
        return _clamp01(value)
    default_threshold = _float_or_none(default.get("threshold"))
    if default_threshold is not None:
        return _clamp01(default_threshold)
    return _rating_to_threshold(passing_score)


def _clamp_rating(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = RUBRIC_SCORE_MIN
    return max(RUBRIC_SCORE_MIN, min(RUBRIC_SCORE_MAX, parsed))


def _threshold_to_rating(value: Any) -> int:
    score = _clamp01(value)
    if score <= 0:
        return RUBRIC_SCORE_MIN
    return _clamp_rating(math.ceil(RUBRIC_SCORE_MIN + score * (RUBRIC_SCORE_MAX - RUBRIC_SCORE_MIN) - 1e-9))


def _score_to_rating(value: Any) -> int:
    return _threshold_to_rating(value)


def _rating_to_threshold(value: Any) -> float:
    rating = _clamp_rating(value)
    return _clamp01((rating - RUBRIC_SCORE_MIN) / (RUBRIC_SCORE_MAX - RUBRIC_SCORE_MIN))


def _tool_use_threshold(tools: dict[str, Any]) -> float:
    return 1.0 if _string_list(tools.get("required")) or _string_list(tools.get("forbidden")) else 0.0


def _accuracy_threshold(accuracy: dict[str, Any]) -> float:
    must_include = _string_list(accuracy.get("must_include"))
    if not must_include:
        return 0.0
    min_must_include = _positive_int(
        accuracy.get("min_must_include"),
        default=min(len(must_include), 2),
    )
    return _clamp01(min_must_include / max(1, len(must_include)))


def _completeness_threshold(completeness: dict[str, Any]) -> float:
    points = _normalized_completeness_points(completeness.get("required_points"))
    if not points:
        return 0.0
    min_score = _float_or_none(completeness.get("min_score"))
    min_required_points = _positive_int(completeness.get("min_required_points"), default=0)
    point_threshold = min_required_points / max(1, len(points)) if min_required_points else 0.0
    return _clamp01(max(min_score if min_score is not None else 0.6, point_threshold))


def _implied_pass_threshold(dimensions: list[dict[str, Any]]) -> float:
    thresholds: list[float] = []
    for dimension in dimensions:
        threshold = _clamp01(dimension.get("threshold"))
        if threshold <= 0:
            continue
        thresholds.append(threshold)
    return _clamp01(mean(thresholds)) if thresholds else 0.0


def _score_rubric(
    rubric: dict[str, Any],
    *,
    metrics: dict[str, Any],
    matched: dict[str, Any],
    response_text: str,
) -> dict[str, Any]:
    dimensions: list[dict[str, Any]] = []
    active_scores: list[float] = []
    active_ratings: list[int] = []
    active_passing_scores: list[int] = []
    for dimension in rubric.get("dimensions") or []:
        score, active, evidence = _score_dimension(dimension.get("id"), metrics, matched, response_text)
        threshold = _clamp01(dimension.get("threshold"))
        rating = _score_to_rating(score)
        passing_score = _clamp_rating(dimension.get("passing_score") or _threshold_to_rating(threshold))
        passed = True if not active else rating >= passing_score
        if active:
            active_scores.append(score)
            active_ratings.append(rating)
            active_passing_scores.append(passing_score)
        dimensions.append(
            {
                "id": clean_text(dimension.get("id")),
                "label": clean_text(dimension.get("label")) or clean_text(dimension.get("id")),
                "standard": clean_text(dimension.get("standard")),
                "requirements": _string_list(dimension.get("requirements")),
                "score": score,
                "score_1_5": rating,
                "passing_score": passing_score,
                "score_scale": {"min": RUBRIC_SCORE_MIN, "max": RUBRIC_SCORE_MAX},
                "threshold": threshold,
                "passed": passed,
                "active": active,
                "scorer": clean_text(dimension.get("scorer")) or "deterministic",
                "evidence": evidence,
            }
        )

    overall_score = mean(active_scores) if active_scores else 1.0
    overall_score_1_5 = mean(active_ratings) if active_ratings else float(RUBRIC_SCORE_MAX)
    pass_threshold = _clamp01(rubric.get("pass_threshold"))
    overall_passing_score = (
        mean(active_passing_scores) if active_passing_scores else float(_threshold_to_rating(pass_threshold))
    )
    gates = _score_gates(_string_list(rubric.get("gates")), response_text, metrics, matched)
    passed = all(item["passed"] for item in gates) and all(item["passed"] for item in dimensions)
    return {
        "overall_score": overall_score,
        "overall_score_1_5": overall_score_1_5,
        "pass_threshold": pass_threshold,
        "overall_passing_score": overall_passing_score,
        "score_scale": {"min": RUBRIC_SCORE_MIN, "max": RUBRIC_SCORE_MAX},
        "passed": passed,
        "gates": gates,
        "dimensions": dimensions,
    }


def _score_dimension(
    dimension_id: Any,
    metrics: dict[str, Any],
    matched: dict[str, Any],
    response_text: str,
) -> tuple[float, bool, dict[str, Any]]:
    dimension_id = clean_text(dimension_id)
    if dimension_id == "tool_use":
        required_count = int(metrics.get("required_tool_count") or 0)
        missing_count = int(metrics.get("required_tool_missing") or 0)
        forbidden_count = int(metrics.get("forbidden_tool_count") or 0)
        forbidden_used = int(metrics.get("forbidden_tool_used") or 0)
        active = bool(required_count or forbidden_count)
        required_score = 1.0 if not required_count else (required_count - missing_count) / required_count
        score = 0.0 if forbidden_used else _clamp01(required_score)
        return score, active, {
            "required_tools": matched.get("required_tools") or [],
            "missing_tools": matched.get("missing_tools") or [],
            "forbidden_tools": matched.get("forbidden_tools") or [],
            "unexpected_tools": matched.get("unexpected_tools") or [],
        }
    if dimension_id == "accuracy":
        must_count = int(metrics.get("must_include_count") or 0)
        forbidden_present = int(metrics.get("forbidden_present") or 0)
        active = bool(must_count or forbidden_present)
        score = 0.0 if forbidden_present else _clamp01(metrics.get("must_include_ratio"))
        return score, active, {
            "included_terms": matched.get("included_terms") or [],
            "missing_terms": matched.get("missing_terms") or [],
            "forbidden_terms": matched.get("forbidden_terms") or [],
        }
    if dimension_id == "completeness":
        point_count = int(metrics.get("completeness_point_count") or 0)
        active = bool(point_count)
        return _clamp01(metrics.get("completeness_score")), active, {
            "matched_points": matched.get("matched_points") or [],
            "missing_points": matched.get("missing_points") or [],
        }
    if dimension_id == "constraints":
        active = True
        forbidden_present = int(metrics.get("forbidden_present") or 0)
        forbidden_tool_used = int(metrics.get("forbidden_tool_used") or 0)
        response_chars = int(metrics.get("response_chars") or 0)
        passed = bool(response_text) and forbidden_present == 0 and forbidden_tool_used == 0
        return 1.0 if passed else 0.0, active, {
            "response_chars": response_chars,
            "forbidden_present": forbidden_present,
            "forbidden_tool_used": forbidden_tool_used,
        }
    return 1.0, False, {}


def _score_gates(
    gate_ids: list[str],
    response_text: str,
    metrics: dict[str, Any],
    matched: dict[str, Any],
) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    for gate_id in gate_ids:
        if gate_id == "non_empty_response":
            passed = bool(response_text)
            reason = "" if passed else "response is empty"
        elif gate_id == "no_forbidden_terms":
            forbidden_terms = matched.get("forbidden_terms") or []
            passed = not forbidden_terms
            reason = "" if passed else "forbidden terms present: " + ", ".join(forbidden_terms[:5])
        elif gate_id == "no_forbidden_tools":
            unexpected_tools = matched.get("unexpected_tools") or []
            passed = not unexpected_tools
            reason = "" if passed else "forbidden tools used: " + ", ".join(unexpected_tools[:5])
        else:
            passed = True
            reason = ""
        gates.append({"id": gate_id, "passed": passed, "reason": reason})
    return gates


def _summarize_dimensions(case_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for result in case_results:
        scorecard = result.get("scorecard") if isinstance(result.get("scorecard"), dict) else {}
        for dimension in scorecard.get("dimensions") or []:
            if not isinstance(dimension, dict) or not dimension.get("active"):
                continue
            dimension_id = clean_text(dimension.get("id"))
            if not dimension_id:
                continue
            bucket = buckets.setdefault(
                dimension_id,
                {
                    "id": dimension_id,
                    "label": clean_text(dimension.get("label")) or dimension_id,
                    "scores": [],
                    "scores_1_5": [],
                    "thresholds": [],
                    "passing_scores": [],
                    "passed_count": 0,
                    "failed_cases": [],
                },
            )
            bucket["scores"].append(float(dimension.get("score") or 0.0))
            bucket["scores_1_5"].append(float(dimension.get("score_1_5") or 0.0))
            bucket["thresholds"].append(float(dimension.get("threshold") or 0.0))
            bucket["passing_scores"].append(float(dimension.get("passing_score") or 0.0))
            if dimension.get("passed"):
                bucket["passed_count"] += 1
            else:
                bucket["failed_cases"].append(str(result.get("id") or ""))

    summary: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for dimension_id, bucket in buckets.items():
        case_count = len(bucket["scores"])
        summary[dimension_id] = {
            "id": dimension_id,
            "label": bucket["label"],
            "case_count": case_count,
            "passed_count": bucket["passed_count"],
            "failed_count": case_count - bucket["passed_count"],
            "pass_rate": bucket["passed_count"] / max(1, case_count),
            "mean_score": mean(bucket["scores"]) if bucket["scores"] else None,
            "mean_score_1_5": mean(bucket["scores_1_5"]) if bucket["scores_1_5"] else None,
            "mean_threshold": mean(bucket["thresholds"]) if bucket["thresholds"] else None,
            "mean_passing_score": mean(bucket["passing_scores"]) if bucket["passing_scores"] else None,
            "score_scale": {"min": RUBRIC_SCORE_MIN, "max": RUBRIC_SCORE_MAX},
            "failed_cases": bucket["failed_cases"],
        }
    return dict(summary)


def _summarize_tag_slices(case_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"cases": [], "scores": []})
    for result in case_results:
        tags = _string_list(result.get("tags")) or ["untagged"]
        scorecard = result.get("scorecard") if isinstance(result.get("scorecard"), dict) else {}
        score = _float_or_none(scorecard.get("overall_score"))
        score_1_5 = _float_or_none(scorecard.get("overall_score_1_5"))
        for tag in tags:
            buckets[tag]["cases"].append(result)
            if score is not None:
                buckets[tag]["scores"].append(score)
            if score_1_5 is not None:
                buckets[tag].setdefault("scores_1_5", []).append(score_1_5)

    slices: list[dict[str, Any]] = []
    for tag, bucket in buckets.items():
        cases = bucket["cases"]
        passed_count = sum(1 for item in cases if item.get("passed"))
        case_count = len(cases)
        slices.append(
            {
                "tag": tag,
                "case_count": case_count,
                "passed_count": passed_count,
                "failed_count": case_count - passed_count,
                "pass_rate": passed_count / max(1, case_count),
                "mean_overall_score": mean(bucket["scores"]) if bucket["scores"] else None,
                "mean_overall_score_1_5": mean(bucket.get("scores_1_5", [])) if bucket.get("scores_1_5") else None,
                "failed_cases": [str(item.get("id") or "") for item in cases if not item.get("passed")],
            }
        )
    return sorted(slices, key=lambda item: (-int(item["failed_count"]), -int(item["case_count"]), str(item["tag"])))


def _normalized_completeness_points(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    points: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            text = clean_text(item)
            if text:
                points.append({"label": text[:80], "any_text_contains": [text]})
            continue
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label") or f"point_{index}")
        any_terms = _string_list(item.get("any_text_contains"))
        all_terms = _string_list(item.get("all_text_contains"))
        if not any_terms and not all_terms:
            text = clean_text(item.get("text") or item.get("description"))
            any_terms = [text] if text else []
        if any_terms or all_terms:
            points.append(
                {
                    "label": label,
                    "any_text_contains": any_terms,
                    "all_text_contains": all_terms,
                }
            )
    return points


def _score_completeness_points(
    response_text: str,
    points: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for point in points:
        all_terms = _string_list(point.get("all_text_contains"))
        any_terms = _string_list(point.get("any_text_contains"))
        all_ok = not all_terms or all(_contains(response_text, term) for term in all_terms)
        any_ok = not any_terms or any(_contains(response_text, term) for term in any_terms)
        preview = {
            "label": clean_text(point.get("label")),
            "all_text_contains": all_terms,
            "any_text_contains": any_terms,
        }
        if all_ok and any_ok:
            matched.append(preview)
        else:
            missing.append(preview)
    return matched, missing


def _normalized_scenario_profile(value: str) -> str:
    normalized = clean_text(value).lower().replace("-", "_")
    return normalized if normalized in SCENARIO_PROFILES else "all"


def _candidate_matches_scenario_profile(
    candidate: dict[str, Any],
    *,
    scenario_profile: str,
    user_text: str,
    assistant_text: str,
) -> bool:
    if scenario_profile == "all":
        return True
    taxonomy = candidate.get("taxonomy") if isinstance(candidate.get("taxonomy"), dict) else {}
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    expected = candidate.get("expected") if isinstance(candidate.get("expected"), dict) else {}
    intent = clean_text(taxonomy.get("intent"))
    tags = set(_string_list(metadata.get("tags")))
    required_tools = _string_list(((expected.get("tools") or {}).get("required")) if isinstance(expected.get("tools"), dict) else [])
    if scenario_profile == "default_qa":
        excluded = {
            "artifact_generation",
            "coding_or_debugging",
            "image_generation",
            "information_lookup",
            "url_understanding",
        }
        risky_tags = {"tool_search", "time_sensitive", "url_input", "tool_or_trace_error"}
        return intent not in excluded and not (tags & risky_tags) and not required_tools
    if scenario_profile == "deep_research":
        return _looks_like_deep_research_case(user_text, assistant_text, intent, tags, required_tools)
    if scenario_profile == "tool_use":
        return bool(required_tools or tags & {"tool_search", "url_input", "time_sensitive"} or intent in {"information_lookup", "url_understanding"})
    if scenario_profile == "coding":
        return intent == "coding_or_debugging"
    return True


def _looks_like_deep_research_case(
    user_text: str,
    assistant_text: str,
    intent: str,
    tags: set[str],
    required_tools: list[str],
) -> bool:
    combined = f"{user_text}\n{assistant_text}".lower()
    terms = (
        "深度研究",
        "调研",
        "研究",
        "报告",
        "资料",
        "来源",
        "引用",
        "检索",
        "竞品",
        "行业",
        "论文",
        "research",
        "deep research",
        "report",
        "sources",
    )
    if any(term in combined for term in terms):
        return intent in {"artifact_generation", "information_lookup", "content_transformation"} or bool(required_tools)
    return intent == "artifact_generation" and bool(tags & {"tool_search", "time_sensitive"})


def _load_conversation_messages(
    db_path: Path,
    *,
    user_id: str | None,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.text_factory = lambda value: value.decode("utf-8", "replace")
    conn.row_factory = sqlite3.Row
    try:
        params: list[Any] = []
        where = ""
        if user_id not in (None, ""):
            where = "where c.user_id = ?"
            params.append(str(user_id))
        rows = conn.execute(
            f"""
            select
                c.id as conversation_id,
                c.user_id as conversation_user_id,
                c.agent_id as conversation_agent_id,
                c.title as conversation_title,
                c.created_at as conversation_created_at,
                c.updated_at as conversation_updated_at,
                m.id as message_id,
                m.role,
                m.content,
                m.skills_used,
                m.citations,
                m.artifacts,
                m.model_used,
                m.runtime,
                m.run_id,
                m.trace_summary,
                m.error_type,
                m.created_at as message_created_at
            from conversations c
            join messages m on m.conversation_id = c.id and m.user_id = c.user_id
            {where}
            order by c.updated_at desc, c.id asc, m.created_at asc, m.id asc
            """,
            params,
        ).fetchall()
    finally:
        conn.close()

    by_conversation: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for row in rows:
        conversation_id = str(row["conversation_id"] or "")
        conversation = by_conversation.setdefault(
            conversation_id,
            {
                "id": conversation_id,
                "user_id": str(row["conversation_user_id"] or "0"),
                "agent_id": str(row["conversation_agent_id"] or "super_chat"),
                "title": str(row["conversation_title"] or ""),
                "created_at": str(row["conversation_created_at"] or ""),
                "updated_at": str(row["conversation_updated_at"] or ""),
                "messages": [],
            },
        )
        conversation["messages"].append(
            {
                "id": int(row["message_id"] or 0),
                "role": str(row["role"] or ""),
                "content": str(row["content"] or ""),
                "skills_used": _json_or_empty(row["skills_used"], []),
                "citations": _json_or_empty(row["citations"], []),
                "artifacts": _json_or_empty(row["artifacts"], []),
                "model_used": str(row["model_used"] or ""),
                "runtime": str(row["runtime"] or ""),
                "run_id": str(row["run_id"] or ""),
                "trace_summary": _json_or_empty(row["trace_summary"], []),
                "error_type": str(row["error_type"] or ""),
                "created_at": str(row["message_created_at"] or ""),
            }
        )
    return list(by_conversation.values())


def _candidate_from_turn(
    conversation: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    user_index: int,
    assistant_index: int,
    max_context_messages: int,
) -> dict[str, Any]:
    user_message = messages[user_index]
    assistant = messages[assistant_index]
    user_text = clean_text(user_message.get("content"))
    assistant_raw_text = str(assistant.get("content") or "")
    assistant_text = clean_text(assistant.get("content"))
    skills_used = _string_list(assistant.get("skills_used"))
    trace_summary = _list_of_dicts(assistant.get("trace_summary"))
    artifacts = _list_of_dicts(assistant.get("artifacts"))
    citations = _list_of_dicts(assistant.get("citations"))
    intent = _infer_intent(user_text, skills_used, trace_summary, artifacts)
    edge_cases = _infer_edge_cases(user_text, assistant, skills_used, trace_summary)
    failure_modes = _infer_failure_modes(user_text, assistant, skills_used, trace_summary)
    answer_result = _expected_answer_results(intent, user_text, assistant_raw_text, artifacts)
    must_include = _expected_accuracy_terms(user_text, answer_result)
    must_not_include = _must_not_include_terms(user_text, intent)
    scenario = _scenario(conversation, user_text, intent)
    case_id = _case_id(conversation["id"], user_message["id"], assistant["id"], assistant.get("run_id"), user_text)
    context_messages = _case_context_messages(messages, user_index, max_context_messages)
    required_tools = _required_tools(intent, user_text, skills_used)
    completeness_points = _default_completeness_points(intent, user_text)
    task_chain = _task_chain(intent, skills_used, artifacts, citations)
    citation_expectations = _expected_citations(intent, required_tools, citations, assistant_raw_text)
    expected = {
        "behavior": _expected_behavior(intent, scenario, required_tools, failure_modes),
        "include": {
            "tool_calls": required_tools,
            "answer_result": answer_result,
            "citations": citation_expectations,
        },
        "tools": {
            "required": required_tools,
            "optional": [],
            "forbidden": [],
        },
        "result": {
            "accuracy": {
                "must_include": must_include,
                "min_must_include": min(len(must_include), 2) if must_include else 0,
                "must_not_include": must_not_include,
            },
            "completeness": {
                "required_points": completeness_points,
                "min_required_points": min(len(completeness_points), 2) if completeness_points else 0,
                "min_score": 0.6 if completeness_points else 0.0,
            },
        },
        # Legacy fields are kept for old UI/files and backwards-compatible eval loading.
        "must_include": must_include,
        "min_must_include": min(len(must_include), 2) if must_include else 0,
        "must_not_include": must_not_include,
        "tool_expectations": [{"name": name, "required": True} for name in required_tools],
    }

    return {
        "id": case_id,
        "type": "conversation_task",
        "status": "candidate",
        "source": {
            "kind": "conversation",
            "conversation_id": conversation["id"],
            "run_id": assistant.get("run_id") or "",
            "message_ids": [user_message["id"], assistant["id"]],
            "user_id": conversation.get("user_id") or "0",
            "created_at": assistant.get("created_at") or "",
        },
        "taxonomy": {
            "scenario": scenario,
            "intent": intent,
            "task_chain": task_chain,
            "edge_cases": edge_cases,
            "failure_modes": failure_modes,
        },
        "input": {
            "messages": context_messages,
            "agent_id": conversation.get("agent_id") or "super_chat",
            "mode_ids": [],
            "disabled_tools": [],
        },
        "expected": expected,
        "rubric": _default_rubric(expected, pass_threshold=DEFAULT_RUBRIC_PASS_THRESHOLD),
        "scoring": {
            "rules": ["contains_any_threshold", "not_contains", "tool_used"],
            "judge_prompt": "",
        },
        "historical_response": {
            "content": assistant_text[:MAX_MESSAGE_CHARS],
            "skills_used": skills_used,
            "model_used": assistant.get("model_used") or "",
            "runtime": assistant.get("runtime") or "",
            "run_id": assistant.get("run_id") or "",
            "error_type": assistant.get("error_type") or "",
            "trace_summary": trace_summary,
            "citations": citations,
        },
        "metadata": {
            "priority": _priority(failure_modes, edge_cases),
            "tags": _tags(intent, edge_cases, failure_modes),
            "language": _language(user_text),
            "auto_confidence": _confidence(user_text, assistant_text, skills_used, failure_modes),
            "dedupe_key": _dedupe_key(user_text, intent),
        },
    }


def _previous_user_index(messages: list[dict[str, Any]], assistant_index: int) -> int | None:
    for index in range(assistant_index - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index
    return None


def _case_context_messages(
    messages: list[dict[str, Any]],
    user_index: int,
    max_context_messages: int,
) -> list[dict[str, str]]:
    start = max(0, user_index - max(0, max_context_messages - 1))
    context: list[dict[str, str]] = []
    for message in messages[start : user_index + 1]:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = clean_text(message.get("content"))
        if not content:
            continue
        context.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    return context


def _meaningful_user_text(text: str) -> bool:
    if len(text) < 3:
        return False
    low_signal = {"/start", "hi", "hello", "你好", "谢谢", "ok", "好的"}
    return text.lower() not in low_signal


def _infer_intent(
    user_text: str,
    skills_used: list[str],
    trace_summary: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> str:
    lowered = user_text.lower()
    if re.search(r"https?://", user_text):
        return "url_understanding"
    if any(skill in {"image_generation_v1"} for skill in skills_used) or any(
        term in user_text for term in ("生图", "画图", "生成图片", "图片")
    ):
        return "image_generation"
    if artifacts or any(term in user_text for term in ("报告", "文档", "保存到网盘", "生成一篇")):
        return "artifact_generation"
    if _tool_used("search", skills_used, trace_summary) or any(
        term in lowered
        for term in (
            "latest",
            "today",
            "news",
            "搜索",
            "查一下",
            "联网",
            "最近",
            "今年",
            "2025",
            "2026",
        )
    ):
        return "information_lookup"
    if any(term in lowered for term in ("bug", "代码", "实现", "函数", "api", "脚本", "repo", "测试")):
        return "coding_or_debugging"
    if any(term in user_text for term in ("总结", "整理", "改写", "润色", "写一")):
        return "content_transformation"
    return "general_qa"


def _infer_edge_cases(
    user_text: str,
    assistant: dict[str, Any],
    skills_used: list[str],
    trace_summary: list[dict[str, Any]],
) -> list[str]:
    edges: list[str] = []
    if _language(user_text) == "mixed":
        edges.append("mixed_language")
    if re.search(r"https?://", user_text):
        edges.append("url_input")
    if re.search(r"\b(20\d{2}|today|latest|recent|current)\b", user_text.lower()) or any(
        term in user_text for term in ("今天", "最新", "最近", "当前", "今年")
    ):
        edges.append("time_sensitive")
    if re.search(r"[A-Za-z]+[^A-Za-z0-9]{0,4}\d+|\d+[^A-Za-z0-9]{0,4}[A-Za-z]+", user_text):
        edges.append("identifier_or_model_number")
    if any(term in user_text for term in ("区别", "分别", "对比", "哪个", "还是")):
        edges.append("comparison_or_disambiguation")
    if _tool_used("search", skills_used, trace_summary):
        edges.append("tool_search")
    if clean_text(assistant.get("error_type")):
        edges.append("error_response")
    return _dedupe_preserve(edges)


def _infer_failure_modes(
    user_text: str,
    assistant: dict[str, Any],
    skills_used: list[str],
    trace_summary: list[dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    error_type = clean_text(assistant.get("error_type"))
    if error_type:
        failures.append(f"assistant_error:{error_type}")
    if _is_current_info_request(user_text) and not _tool_used("search", skills_used, trace_summary):
        failures.append("possible_stale_answer_without_search")
    if _trace_has_errors(trace_summary):
        failures.append("tool_or_trace_error")
    lowered = user_text.lower()
    if "dunlop" in lowered and any(term in user_text for term in ("吉他", "指板", "柠檬油", "护理")):
        failures.append("brand_ambiguity_pollution")
    if "成人" in user_text and "钢琴" in user_text:
        failures.append("sensitive_term_pollution")
    return _dedupe_preserve(failures)


def _task_chain(
    intent: str,
    skills_used: list[str],
    artifacts: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> list[str]:
    chain = ["理解用户目标和上下文"]
    if intent == "url_understanding":
        chain.append("读取或解析用户提供的链接")
    if intent == "information_lookup" or "search" in skills_used:
        chain.append("检索外部信息并筛选来源")
    if citations:
        chain.append("引用可核验来源")
    if artifacts or intent == "artifact_generation":
        chain.append("生成可保存的结构化产物")
    if intent == "coding_or_debugging":
        chain.append("定位实现约束并给出可执行改动")
    chain.append("组织最终回答")
    return chain


def _expected_answer_results(
    intent: str,
    user_text: str,
    assistant_text: str,
    artifacts: list[dict[str, Any]],
) -> list[str]:
    facts: list[str] = []
    facts.extend(_operation_result_facts(assistant_text, artifacts))
    facts.extend(_markdown_table_facts(assistant_text))
    facts.extend(_response_sentence_facts(intent, user_text, assistant_text))
    if not facts:
        facts.append(f"回答需覆盖用户请求：{_text_preview(user_text, 90)}")
    return _dedupe_preserve([fact for fact in (_compact_expectation_text(item) for item in facts) if fact])[:6]


def _operation_result_facts(assistant_text: str, artifacts: list[dict[str, Any]]) -> list[str]:
    facts: list[str] = []
    for artifact in artifacts[:3]:
        name = clean_text(artifact.get("name") or artifact.get("title") or artifact.get("item_id"))
        kind = clean_text(artifact.get("kind") or artifact.get("type"))
        if name:
            facts.append(f"产物已生成：{name}" + (f"（{kind}）" if kind else ""))

    for line in _clean_response_lines(assistant_text):
        lowered = line.lower()
        has_operation = any(
            term in line
            for term in ("已保存", "成功保存", "已经保存", "已成功", "已经成功", "已读取", "成功读取", "文件名")
        ) or any(term in lowered for term in ("read_drive", "write_drive", "saved", "created"))
        if not has_operation:
            continue
        if not any(term in line for term in ("报告", "文件", "网盘", "Markdown", "读取", "保存", ".md", ".doc", ".pdf")):
            continue
        operation_fact = _normalized_operation_fact(line)
        if operation_fact:
            facts.append(operation_fact)
    return facts


def _normalized_operation_fact(line: str) -> str:
    lowered = line.lower()
    if "已截断" in line and "文件" not in line:
        return ""
    if "read_drive" in lowered and "读取" in line:
        match = re.search(r"文件[:：]\s*([^。；;]+)", line)
        if match:
            return f"read_drive 已读取文件：{_strip_markdown(match.group(1))}"
    return line


def _markdown_table_facts(text: str) -> list[str]:
    facts: list[str] = []
    headers: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or "|" not in line[1:]:
            if facts and not line:
                headers = []
            continue
        cells = [_strip_markdown(cell) for cell in line.strip("|").split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r":?-{2,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        if not headers:
            headers = cells
            continue
        first = cells[0]
        if _looks_like_table_header(first):
            headers = cells
            continue
        details = cells[1:]
        if not first or not details:
            continue
        facts.append(f"{first}：{'；'.join(details[:2])}")
        if len(facts) >= 5:
            break
    return facts


def _response_sentence_facts(intent: str, user_text: str, assistant_text: str) -> list[str]:
    facts: list[str] = []
    salient = _salient_terms(user_text)
    for line in _clean_response_lines(assistant_text):
        if _skip_answer_fact_line(line):
            continue
        if _line_mentions_any(line, salient) or _line_matches_intent_result(intent, line):
            facts.append(line)
        if len(facts) >= 6:
            break
    return facts


def _clean_response_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = _strip_markdown(raw_line)
        if not line:
            continue
        if len(line) > 180:
            parts = re.split(r"(?<=[。！？.!?])\s+", line)
            for part in parts:
                compact = _strip_markdown(part)
                if compact:
                    lines.append(compact)
        else:
            lines.append(line)
    if lines:
        return lines
    compact_text = _strip_markdown(text)
    return [_strip_markdown(item) for item in re.split(r"(?<=[。！？.!?])\s+", compact_text) if _strip_markdown(item)]


def _strip_markdown(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("~~", "")
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"^\s{0,3}[-*+]\s+", "", text)
    text = re.sub(r"^\s{0,3}>\s?", "", text)
    text = re.sub(r"^[^\w\u4e00-\u9fff]+", "", text)
    text = text.strip(" \t\r\n-—|")
    return clean_text(text)


def _compact_expectation_text(value: Any, *, max_chars: int = 120) -> str:
    text = _strip_markdown(value)
    text = re.sub(r"https?://\S+", lambda match: _domain_from_url(match.group(0)) or match.group(0), text)
    text = text.strip("，。！？、：；,.!?;: ")
    if not text or _skip_answer_fact_line(text):
        return ""
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rstrip("，。！？、：；,.!?;: ")
    return f"{trimmed}..."


def _looks_like_table_header(value: str) -> bool:
    lowered = value.lower()
    return lowered in {"名称", "瓶身", "项目", "维度", "指标", "name", "item", "title"} or "是什么" in value


def _skip_answer_fact_line(line: str) -> bool:
    if not line or len(line) < 4:
        return True
    lowered = line.lower()
    if re.fullmatch(r"[-=*_]{3,}", line):
        return True
    if lowered.startswith(("http://", "https://", "来源:", "source:")):
        return True
    if "connection error" in lowered and "read_drive" in lowered:
        return True
    if line.count("|") >= 2:
        return True
    if any(line.startswith(prefix) for prefix in ("好的", "可以", "老板", "注意到", "要不要")):
        return True
    low_value_prefixes = (
        "下面是",
        "以下是",
        "这里是",
        "我会",
        "我来",
        "收工",
    )
    if any(line.startswith(prefix) and len(line) < 28 for prefix in low_value_prefixes):
        return True
    return False


def _line_mentions_any(line: str, terms: list[str]) -> bool:
    lowered = line.lower()
    return any(term and term.lower() in lowered for term in terms)


def _line_matches_intent_result(intent: str, line: str) -> bool:
    if intent == "artifact_generation":
        return any(term in line for term in ("已保存", "文件名", "报告", "Markdown", "网盘", "路径"))
    if intent == "information_lookup":
        return any(term in line for term in ("结论", "用途", "区别", "对比", "来源", "截至", "最新"))
    if intent == "coding_or_debugging":
        return any(term in line for term in ("修复", "实现", "测试", "报错", "原因"))
    return False


def _expected_accuracy_terms(user_text: str, answer_result: list[str]) -> list[str]:
    terms: list[str] = []
    terms.extend(_salient_terms(user_text)[:4])
    joined_results = " ".join(answer_result)
    terms.extend(re.findall(r"\b[A-Za-z][A-Za-z0-9_.+-]*(?:\s+No\.\s*\d+)?\b", joined_results))
    terms.extend(re.findall(r"\bNo\.\s*\d+\b", joined_results))
    for phrase in (
        "Formula No. 65",
        "No. 01",
        "No. 02",
        "漆面",
        "指板",
        "清洁剂",
        "护理油",
        "柠檬油",
        "文件名",
        "网盘",
        "Markdown",
        "来源",
    ):
        if phrase in joined_results:
            terms.append(phrase)
    return _dedupe_preserve([term for term in terms if _useful_accuracy_term(term)])[:8]


def _useful_accuracy_term(term: str) -> bool:
    text = clean_text(term).strip("，。！？、：；（）()[]【】")
    if not text or text.lower() in STOPWORDS or text in STOPWORDS:
        return False
    if text.lower() in {"formula", "source", "no", "connection", "error", "kb", "md"}:
        return False
    if text.lower() in {"markdown"}:
        return text == "Markdown"
    return len(text) >= 2


def _expected_citations(
    intent: str,
    required_tools: list[str],
    citations: list[dict[str, Any]],
    assistant_text: str = "",
) -> list[str]:
    if citations:
        expectations: list[str] = []
        for citation in citations[:5]:
            title = clean_text(citation.get("title") or citation.get("source") or "")
            url = clean_text(citation.get("url"))
            domain = _domain_from_url(url)
            if title and domain:
                expectations.append(f"引用来源：{_text_preview(title, 70)}（{domain}）")
            elif title:
                expectations.append(f"引用来源：{_text_preview(title, 90)}")
            elif domain:
                expectations.append(f"引用来源：{domain}")
        return _dedupe_preserve(expectations)[:5] or ["引用可核验来源"]
    embedded = _embedded_source_expectations(assistant_text)
    if embedded:
        return embedded[:5]
    if intent == "information_lookup" or "search" in required_tools:
        return ["必要时给出来源或说明依据"]
    return []


def _embedded_source_expectations(text: str) -> list[str]:
    expectations: list[str] = []
    for url in re.findall(r"https?://[^\s)）]+", str(text or "")):
        domain = _domain_from_url(url)
        if domain:
            expectations.append(f"引用报告内来源：{domain}")
    for match in re.finditer(r"(?:主要来源|来源)[:：]\s*([^。\n\r]+)", str(text or "")):
        source_text = _strip_markdown(match.group(1))
        if source_text and not source_text.startswith("http"):
            expectations.append(f"保留报告内来源：{_text_preview(source_text, 90)}")
    return _dedupe_preserve(expectations)


def _domain_from_url(url: str) -> str:
    value = clean_text(url).strip("，。！？、：；,.!?;:)]}）】")
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.netloc and re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value):
        parsed = urlparse(f"https://{value}")
    return parsed.netloc.lower().removeprefix("www.")



def _expected_behavior(
    intent: str,
    scenario: str,
    required_tools: list[str],
    failure_modes: list[str],
) -> str:
    parts = [f"围绕「{scenario}」完成用户任务"]
    if required_tools:
        parts.append("必要时调用 " + ", ".join(required_tools))
    if "possible_stale_answer_without_search" in failure_modes:
        parts.append("涉及实时信息时应先验证再回答")
    if any(item.endswith("pollution") or "pollution" in item for item in failure_modes):
        parts.append("避免被歧义或污染语义带偏")
    return "；".join(parts) + "。"


def _scenario(conversation: dict[str, Any], user_text: str, intent: str) -> str:
    raw_title = str(conversation.get("title") or "")
    title = clean_text(raw_title)
    intent_label = {
        "information_lookup": "信息检索",
        "url_understanding": "链接理解",
        "image_generation": "图像生成",
        "artifact_generation": "产物生成",
        "coding_or_debugging": "代码/调试",
        "content_transformation": "内容整理",
    }.get(intent, "通用问答")
    if _meaningful_conversation_title(title, raw_title):
        return _text_preview(title, 90)
    return f"{intent_label}: {_text_preview(user_text, 70)}"


def _meaningful_conversation_title(title: str, raw_title: str) -> bool:
    if not title or "\ufffd" in raw_title:
        return False
    lowered = title.lower()
    if lowered in {"new conversation", "untitled", "无标题", "新对话"}:
        return False
    if len(title) < 4 and not re.search(r"[A-Za-z]{3,}|\d", title):
        return False
    low_signal = {"歪", "测试", "继续", "可以", "好的", "随便聊聊"}
    return title not in low_signal and len(title) <= 48


def _required_tools(intent: str, user_text: str, skills_used: list[str]) -> list[str]:
    tools: list[str] = []
    if intent == "information_lookup" and ("search" in skills_used or _is_current_info_request(user_text)):
        tools.append("search")
    if intent == "url_understanding" and "open_url" in skills_used:
        tools.append("open_url")
    return tools


def _default_completeness_points(intent: str, user_text: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    if intent == "information_lookup":
        points.append(
            {
                "label": "answer_core_question",
                "any_text_contains": _salient_terms(user_text)[:3],
            }
        )
        if _is_current_info_request(user_text):
            points.append(
                {
                    "label": "mention_time_or_source_sensitivity",
                    "any_text_contains": ["最新", "截至", "来源", "搜索", "today", "latest"],
                }
            )
    if any(term in user_text for term in ("区别", "分别", "对比", "哪个", "还是")):
        points.append(
            {
                "label": "compare_or_distinguish_options",
                "any_text_contains": ["区别", "分别", "对比", "用途", "适合", "不适合"],
            }
        )
    if any(term in user_text for term in ("如何", "怎么", "步骤", "流程", "使用")):
        points.append(
            {
                "label": "give_actionable_steps",
                "any_text_contains": ["步骤", "流程", "先", "然后", "最后", "1.", "①"],
            }
        )
    if intent == "artifact_generation":
        points.append(
            {
                "label": "produce_structured_artifact",
                "any_text_contains": ["#", "##", "|", "- ", "总结", "报告"],
            }
        )
    return [point for point in points if point.get("any_text_contains") or point.get("all_text_contains")]


def _must_not_include_terms(user_text: str, intent: str) -> list[str]:
    lowered = user_text.lower()
    terms: list[str] = []
    if "dunlop" in lowered and any(term in user_text for term in ("吉他", "指板", "柠檬油", "护理")):
        terms.extend(["轮胎", "tyres", "tires"])
    if "成人" in user_text and "钢琴" in user_text:
        terms.extend(["成人视频", "成人用品", "porn"])
    if intent == "information_lookup":
        terms.extend(["无法联网但", "我不能访问互联网"])
    return _dedupe_preserve(terms)


def _salient_terms(text: str) -> list[str]:
    terms: list[str] = []
    for phrase in CJK_KEY_PHRASES:
        if phrase in text:
            terms.append(phrase)
    for item in re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{2,}|[\u4e00-\u9fff]{2,}", text):
        cleaned = clean_text(item).strip("，。！？、：；（）()[]【】")
        if not cleaned or cleaned.lower() in STOPWORDS or cleaned in STOPWORDS:
            continue
        if len(cleaned) > 6 and re.fullmatch(r"[\u4e00-\u9fff]+", cleaned):
            terms.extend(_split_cjk_phrase(cleaned))
        else:
            terms.append(cleaned)
    return _dedupe_preserve(terms)[:6]


def _split_cjk_phrase(value: str) -> list[str]:
    chunks = []
    for size in (4, 3, 2):
        if len(chunks) >= 4:
            break
        for index in range(0, len(value) - size + 1, size):
            chunk = value[index : index + size]
            if chunk not in STOPWORDS and chunk[:1] not in CJK_CHUNK_PREFIX_STOP:
                chunks.append(chunk)
            if len(chunks) >= 4:
                break
    return chunks or [value[:8]]


def _priority(failure_modes: list[str], edge_cases: list[str]) -> str:
    if failure_modes:
        return "p1"
    if any(edge in edge_cases for edge in ("time_sensitive", "identifier_or_model_number", "tool_search")):
        return "p2"
    return "p3"


def _tags(intent: str, edge_cases: list[str], failure_modes: list[str]) -> list[str]:
    tags = [intent, *edge_cases]
    for failure in failure_modes:
        tags.append(failure.split(":", 1)[0])
    return _dedupe_preserve(tags)[:12]


def _confidence(
    user_text: str,
    assistant_text: str,
    skills_used: list[str],
    failure_modes: list[str],
) -> float:
    score = 0.45
    if len(user_text) >= 12:
        score += 0.12
    if len(assistant_text) >= 80:
        score += 0.12
    if skills_used:
        score += 0.12
    if failure_modes:
        score += 0.12
    return round(min(score, 0.95), 2)


def _language(text: str) -> str:
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    if has_latin:
        return "en"
    return "unknown"


def _is_current_info_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"\b(20\d{2}|today|latest|recent|current|news)\b", lowered)
        or any(term in text for term in ("今天", "最新", "最近", "当前", "今年", "实时"))
    )


def _tool_used(
    tool: str,
    skills_used: list[str],
    trace_summary: list[dict[str, Any]],
) -> bool:
    tool = tool.lower().strip()
    if any(str(skill).lower().strip() == tool for skill in skills_used):
        return True
    for event in trace_summary:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        event_type = str(event.get("type") or "").lower()
        name = str(payload.get("name") or payload.get("tool") or "").lower()
        if name == tool:
            return True
        if tool == "search" and event_type.startswith("search."):
            return True
    return False


def _trace_has_errors(trace_summary: list[dict[str, Any]]) -> bool:
    for event in trace_summary:
        status = str(event.get("status") or "").lower()
        event_type = str(event.get("type") or "").lower()
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if status in {"error", "failed"} or event_type.endswith(".failed"):
            return True
        if clean_text(payload.get("error_message") or payload.get("error_type")):
            return True
    return False


def _case_id(
    conversation_id: str,
    user_message_id: int,
    assistant_message_id: int,
    run_id: str,
    user_text: str,
) -> str:
    digest = hashlib.sha1(
        f"{conversation_id}|{user_message_id}|{assistant_message_id}|{run_id}|{user_text}".encode("utf-8")
    ).hexdigest()[:10]
    slug = "_".join(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", user_text.lower())[:6])
    return f"conv_{digest}_{slug[:42] or 'case'}"


def _dedupe_key(user_text: str, intent: str) -> str:
    normalized = re.sub(r"\s+", " ", user_text.lower()).strip()
    return hashlib.sha1(f"{intent}|{normalized}".encode("utf-8")).hexdigest()


def clean_text(value: Any) -> str:
    text = str(value or "").replace("\ufffd", "").replace("\x00", "")
    return re.sub(r"\s+", " ", text).strip()


def _text_preview(value: Any, max_chars: int) -> str:
    text = clean_text(value)
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rstrip("，。！？、：；,.!?;: ")
    return f"{trimmed}..."


def _contains(text: str, needle: str) -> bool:
    return needle.strip().lower() in text.lower()


def _json_or_empty(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return fallback
    return parsed


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = clean_text(item)
        if text:
            result.append(text)
    return result


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_float(value: Any, *, default: float) -> float:
    parsed = _float_or_none(value)
    if parsed is None or parsed < 0:
        return default
    return parsed


def _clamp01(value: Any) -> float:
    parsed = _float_or_none(value)
    if parsed is None:
        return 0.0
    return max(0.0, min(1.0, parsed))


def _metric_mean(metrics: list[dict[str, Any]], key: str) -> float | None:
    values = [float(item[key]) for item in metrics if item.get(key) is not None]
    return mean(values) if values else None


def _mean_float(values: Any) -> float | None:
    parsed = [_float_or_none(item) for item in values]
    kept = [item for item in parsed if item is not None]
    return mean(kept) if kept else None
