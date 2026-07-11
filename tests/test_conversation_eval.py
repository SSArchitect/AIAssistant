import sqlite3
import importlib.util
from pathlib import Path

from agent.eval.conversation import (
    _apply_llm_candidate_payload,
    build_conversation_eval_candidates,
    evaluate_conversation_case,
    summarize_conversation_eval,
)


def _load_collect_script_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "collect_conversation_eval_cases.py"
    spec = importlib.util.spec_from_file_location("collect_conversation_eval_cases", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_build_conversation_eval_candidates_from_sqlite(tmp_path):
    db_path = tmp_path / "assistant.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            create table conversations (
                id text primary key,
                user_id text,
                agent_id text,
                title text,
                created_at text,
                updated_at text
            );
            create table messages (
                id integer primary key autoincrement,
                conversation_id text,
                user_id text,
                role text,
                content text,
                skills_used text,
                citations text,
                artifacts text,
                model_used text,
                runtime text,
                run_id text,
                trace_summary text,
                error_type text,
                created_at text
            );
            """
        )
        conn.execute(
            "insert into conversations values (?, ?, ?, ?, ?, ?)",
            ("conv-1", "user-a", "super_chat", "Dunlop 指板护理", "2026-01-01", "2026-01-02"),
        )
        conn.execute(
            """
            insert into messages
            (conversation_id, user_id, role, content, skills_used, citations, artifacts, model_used, runtime, run_id, trace_summary, error_type, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "conv-1",
                "user-a",
                "user",
                "Dunlop 65 指板柠檬油和轮胎品牌会混淆，帮我查官方用途",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            """
            insert into messages
            (conversation_id, user_id, role, content, skills_used, citations, artifacts, model_used, runtime, run_id, trace_summary, error_type, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "conv-1",
                "user-a",
                "assistant",
                (
                    "| 瓶身 | 真实身份 | 干什么的 |\n"
                    "|---|---|---|\n"
                    "| Formula No. 65 | 琴体漆面清洁+抛光剂 | 清洁漆面，对木头指板无效 |\n"
                    "| No. 01 | 指板清洁剂 | 去脏 |\n"
                    "| No. 02 | 指板护理油 | 玫瑰木/乌木补油 |"
                ),
                '["search"]',
                '[{"title":"Dunlop Fingerboard Care Kit","url":"https://example.com/dunlop-care","snippet":"Dunlop guitar care"}]',
                "[]",
                "MiniMax-M3",
                "self",
                "run-1",
                '[{"type":"search.recall.completed","status":"completed","payload":{"query":"Dunlop 65 指板柠檬油"}}]',
                "",
                "2026-01-01T00:00:10Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    candidates, skipped = build_conversation_eval_candidates(db_path, user_id="user-a")

    assert skipped == {}
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["type"] == "conversation_task"
    assert candidate["taxonomy"]["intent"] == "information_lookup"
    assert "brand_ambiguity_pollution" in candidate["taxonomy"]["failure_modes"]
    assert "reasoning_chain" not in candidate["expected"]["include"]
    assert candidate["expected"]["include"]["tool_calls"] == ["search"]
    assert any("Formula No. 65" in item and "漆面" in item for item in candidate["expected"]["include"]["answer_result"])
    assert any("No. 01" in item and "指板" in item for item in candidate["expected"]["include"]["answer_result"])
    assert "引用可核验来源" not in candidate["expected"]["include"]["citations"]
    assert any("Dunlop Fingerboard Care Kit" in item for item in candidate["expected"]["include"]["citations"])
    assert any("指板" in item for item in candidate["expected"]["result"]["accuracy"]["must_include"])
    assert candidate["expected"]["tools"]["required"] == ["search"]
    assert "accuracy" in candidate["expected"]["result"]
    assert "completeness" in candidate["expected"]["result"]
    assert candidate["rubric"]["pass_threshold"] == 0.75
    assert [item["id"] for item in candidate["rubric"]["dimensions"]] == [
        "tool_use",
        "accuracy",
        "completeness",
        "constraints",
    ]
    for dimension in candidate["rubric"]["dimensions"]:
        assert "weight" not in dimension
        assert dimension["standard"]
        assert isinstance(dimension["requirements"], list)
        assert 1 <= dimension["passing_score"] <= 5
    assert {"name": "search", "required": True} in candidate["expected"]["tool_expectations"]
    assert "轮胎" in candidate["expected"]["must_not_include"]


def test_collect_script_loads_runtime_settings_from_sqlite(tmp_path):
    db_path = tmp_path / "assistant.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            create table settings (
                key text primary key,
                value text
            );
            """
        )
        conn.executemany(
            "insert into settings values (?, ?)",
            [
                ("llm.default_provider", "minimax"),
                ("llm.minimax.api_key", "secret-value"),
                ("llm.minimax.model", "MiniMax-M3"),
                ("admin.password", "should-not-load"),
                ("unrelated", "ignored"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    module = _load_collect_script_module()
    settings = module._runtime_settings_from_db(db_path)

    assert settings["llm.default_provider"] == "minimax"
    assert settings["llm.minimax.api_key"] == "secret-value"
    assert settings["llm.minimax.model"] == "MiniMax-M3"
    assert "admin.password" not in settings
    assert "unrelated" not in settings


def test_llm_payload_does_not_downgrade_detailed_answer_result():
    candidate = {
        "taxonomy": {"scenario": "Dunlop 保养剂", "intent": "information_lookup"},
        "expected": {
            "include": {
                "tool_calls": ["search"],
                "answer_result": [
                    "Formula No. 65：琴体漆面清洁+抛光剂；对木头指板无效",
                    "No. 01：指板清洁剂；用于去除汗渍和油泥",
                    "No. 02：指板护理油；用于玫瑰木/乌木补油",
                ],
                "citations": ["引用来源：Dunlop Fingerboard Care Kit（example.com）"],
            },
            "tools": {"required": ["search"], "forbidden": []},
            "result": {
                "accuracy": {"must_include": ["Formula No. 65", "No. 01", "No. 02"], "min_must_include": 2},
                "completeness": {"required_points": [], "min_required_points": 0, "min_score": 0.0},
            },
        },
        "metadata": {},
    }

    _apply_llm_candidate_payload(
        candidate,
        {
            "scenario": "查询Dunlop65/01/02三款电吉他保养剂的作用及使用方法",
            "intent": "information_lookup",
            "expected": {
                "include": {
                    "tool_calls": ["search"],
                    "answer_result": ["电吉他", "吉他", "保养剂", "清洁"],
                    "citations": ["引用来源：Dunlop Fingerboard Care Kit（example.com）"],
                },
                "result": {
                    "accuracy": {"must_include": ["电吉他", "吉他", "保养剂", "清洁"], "min_must_include": 2},
                },
            },
        },
    )

    answer_result = candidate["expected"]["include"]["answer_result"]
    assert any("Formula No. 65" in item and "指板无效" in item for item in answer_result)
    assert not all(item in {"电吉他", "吉他", "保养剂", "清洁"} for item in answer_result)


def test_candidate_quality_gate_filters_low_value_turns(tmp_path):
    db_path = tmp_path / "assistant.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            create table conversations (
                id text primary key,
                user_id text,
                agent_id text,
                title text,
                created_at text,
                updated_at text
            );
            create table messages (
                id integer primary key autoincrement,
                conversation_id text,
                user_id text,
                role text,
                content text,
                skills_used text,
                citations text,
                artifacts text,
                model_used text,
                runtime text,
                run_id text,
                trace_summary text,
                error_type text,
                created_at text
            );
            """
        )
        for conv_id, title in (("conv-low", "低价值确认"), ("conv-good", "最新政策检索")):
            conn.execute(
                "insert into conversations values (?, ?, ?, ?, ?, ?)",
                (conv_id, "user-a", "super_chat", title, "2026-01-01", "2026-01-02"),
            )
        rows = [
            ("conv-low", "user", "帮我看看", "", "", "", "", "", "", "", "2026-01-01T00:00:00Z"),
            ("conv-low", "assistant", "好的，我看看。", "[]", "[]", "[]", "MiniMax-M3", "self", "run-low", "", "2026-01-01T00:00:02Z"),
            ("conv-good", "user", "帮我查一下 2026 年最新 AI agent 评测框架趋势", "", "", "", "", "", "", "", "2026-01-01T00:01:00Z"),
            (
                "conv-good",
                "assistant",
                "我检索后总结：需要关注可回归用例、工具调用准确性、引用完整性和多维评分。",
                '["search"]',
                "[]",
                "[]",
                "MiniMax-M3",
                "self",
                "run-good",
                '[{"type":"search.recall.completed","status":"completed","payload":{"query":"2026 AI agent eval framework"}}]',
                "2026-01-01T00:01:10Z",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                insert into messages
                (conversation_id, user_id, role, content, skills_used, citations, artifacts, model_used, runtime, run_id, trace_summary, error_type, created_at)
                values (?, 'user-a', ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)
                """,
                row,
            )
        conn.commit()
    finally:
        conn.close()

    candidates, skipped = build_conversation_eval_candidates(
        db_path,
        user_id="user-a",
        quality_profile="balanced",
    )

    assert len(candidates) == 1
    assert candidates[0]["source"]["run_id"] == "run-good"
    assert candidates[0]["metadata"]["candidate_quality_score"] >= 0.55
    assert skipped["quality_below:balanced"] == 1


def test_evaluate_conversation_case_scores_terms_and_tools():
    case = {
        "id": "case-1",
        "type": "conversation_task",
        "taxonomy": {"scenario": "成人钢琴教材", "intent": "information_lookup"},
        "input": {"messages": [{"role": "user", "content": "成人钢琴教材推荐"}]},
        "metadata": {"tags": ["piano_learning", "tool_search"], "priority": "p1"},
        "expected": {
            "tools": {
                "required": ["search"],
                "forbidden": ["image_generation_v1"],
            },
            "result": {
                "accuracy": {
                    "must_include": ["成人", "钢琴", "教材"],
                    "min_must_include": 2,
                    "must_not_include": ["成人视频"],
                },
                "completeness": {
                    "required_points": [
                        {
                            "label": "教材路线",
                            "any_text_contains": ["拜厄", "哈农", "车尔尼"],
                        },
                        {
                            "label": "成人学习者",
                            "all_text_contains": ["成人", "钢琴"],
                        },
                    ],
                    "min_required_points": 2,
                    "min_score": 1.0,
                },
            },
        },
    }

    failed = evaluate_conversation_case(
        case,
        response_text="成人视频和成人用品很多。",
        skills_used=[],
        events=[],
    )
    passed = evaluate_conversation_case(
        case,
        response_text="成人钢琴教材可以从拜厄和哈农开始。",
        skills_used=["search"],
        events=[],
    )
    summary = summarize_conversation_eval([failed, passed])

    assert not failed["passed"]
    assert any("forbidden" in failure for failure in failed["failures"])
    assert any("required tools missing" in failure for failure in failed["failures"])
    assert passed["passed"]
    assert passed["metrics"]["completeness_score"] == 1.0
    assert passed["scorecard"]["overall_score"] == 1.0
    assert passed["scorecard"]["overall_score_1_5"] == 5
    assert [item["id"] for item in passed["scorecard"]["dimensions"]] == [
        "tool_use",
        "accuracy",
        "completeness",
        "constraints",
    ]
    for dimension in passed["scorecard"]["dimensions"]:
        assert "weight" not in dimension
        assert dimension["standard"]
        assert 1 <= dimension["score_1_5"] <= 5
        assert 1 <= dimension["passing_score"] <= 5
    assert summary["case_count"] == 2
    assert summary["passed_count"] == 1
    assert summary["mean_overall_score"] == 0.5
    assert summary["mean_overall_score_1_5"] == 3
    assert summary["mean_completeness_score"] == 0.5
    assert summary["dimension_scores"]["accuracy"]["pass_rate"] == 0.5
    assert summary["dimension_scores"]["tool_use"]["mean_score"] == 0.5
    assert summary["dimension_scores"]["tool_use"]["mean_score_1_5"] == 3
    assert summary["dimension_scores"]["tool_use"]["mean_passing_score"] == 5
    assert summary["tag_slices"][0]["case_count"] == 2
