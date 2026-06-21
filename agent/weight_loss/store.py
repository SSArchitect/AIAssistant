from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_USER_ID = "0"
LEGACY_DEFAULT_SCOPE = "__default_user__"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_database_path() -> Path:
    from agent.config import settings

    configured = Path(settings.assistant_database_path)
    if configured.is_absolute():
        return configured
    return Path(__file__).resolve().parents[2] / configured


def _iso(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return utc_now()
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _local_date(value: str) -> str:
    return _parse_datetime(value).astimezone(LOCAL_TZ).date().isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


class WeightLossStore:
    """Small SQLite-backed store for the weight-loss agent.

    The gateway already owns the app database. The Python agent creates only its
    own namespaced tables, so the feature can persist food logs without changing
    the Go conversation schema.
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else default_database_path()
        self._lock = RLock()
        self._initialized = False

    def ensure_schema(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS weight_loss_profiles (
                        conversation_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL DEFAULT '0',
                        daily_calorie_goal INTEGER,
                        maintenance_calories INTEGER,
                        target_deficit INTEGER,
                        current_weight_kg REAL,
                        target_weight_kg REAL,
                        height_cm REAL,
                        age_years INTEGER,
                        sex TEXT,
                        activity_level TEXT,
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS weight_loss_meals (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        user_id TEXT NOT NULL DEFAULT '0',
                        logged_at TEXT NOT NULL,
                        meal_name TEXT,
                        meal_type TEXT,
                        total_calories INTEGER NOT NULL,
                        calorie_min INTEGER,
                        calorie_max INTEGER,
                        protein_g REAL,
                        carbs_g REAL,
                        fat_g REAL,
                        confidence REAL,
                        source TEXT,
                        notes TEXT,
                        image_count INTEGER NOT NULL DEFAULT 0,
                        raw_json TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_weight_loss_meals_conversation_logged
                        ON weight_loss_meals(conversation_id, logged_at);

                    CREATE TABLE IF NOT EXISTS weight_loss_exercises (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        user_id TEXT NOT NULL DEFAULT '0',
                        logged_at TEXT NOT NULL,
                        activity TEXT,
                        calories_burned INTEGER NOT NULL,
                        duration_min REAL,
                        notes TEXT,
                        raw_json TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_weight_loss_exercises_conversation_logged
                        ON weight_loss_exercises(conversation_id, logged_at);
                    """
                )
                self._ensure_columns(conn)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_weight_loss_meals_user_logged ON weight_loss_meals(user_id, logged_at)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_weight_loss_exercises_user_logged ON weight_loss_exercises(user_id, logged_at)"
                )
                self._migrate_user_scope(conn)
            self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _normalize_user_id(self, user_id: str | int | None = None) -> str:
        value = str(user_id if user_id not in (None, "") else DEFAULT_USER_ID).strip()
        return value or DEFAULT_USER_ID

    def _scope_id(self, user_id: str | int | None = None) -> str:
        return f"user:{self._normalize_user_id(user_id)}"

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(weight_loss_profiles)").fetchall()}
        if "user_id" not in columns:
            conn.execute("ALTER TABLE weight_loss_profiles ADD COLUMN user_id TEXT NOT NULL DEFAULT '0'")
        if "age_years" not in columns:
            conn.execute("ALTER TABLE weight_loss_profiles ADD COLUMN age_years INTEGER")
        meal_columns = {row["name"] for row in conn.execute("PRAGMA table_info(weight_loss_meals)").fetchall()}
        if "user_id" not in meal_columns:
            conn.execute("ALTER TABLE weight_loss_meals ADD COLUMN user_id TEXT NOT NULL DEFAULT '0'")
        exercise_columns = {row["name"] for row in conn.execute("PRAGMA table_info(weight_loss_exercises)").fetchall()}
        if "user_id" not in exercise_columns:
            conn.execute("ALTER TABLE weight_loss_exercises ADD COLUMN user_id TEXT NOT NULL DEFAULT '0'")

    def _migrate_user_scope(self, conn: sqlite3.Connection) -> None:
        default_scope = self._scope_id(DEFAULT_USER_ID)
        default_profile = conn.execute(
            "SELECT conversation_id FROM weight_loss_profiles WHERE conversation_id = ?",
            (default_scope,),
        ).fetchone()
        if default_profile is None:
            latest = conn.execute(
                """
                SELECT conversation_id FROM weight_loss_profiles
                WHERE conversation_id = ? OR user_id = ? OR conversation_id NOT LIKE 'user:%'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (LEGACY_DEFAULT_SCOPE, DEFAULT_USER_ID),
            ).fetchone()
            if latest is not None:
                conn.execute(
                    "UPDATE weight_loss_profiles SET conversation_id = ?, user_id = ? WHERE conversation_id = ?",
                    (default_scope, DEFAULT_USER_ID, latest["conversation_id"]),
                )
        conn.execute(
            "UPDATE weight_loss_profiles SET user_id = ? WHERE conversation_id = ?",
            (DEFAULT_USER_ID, default_scope),
        )
        conn.execute(
            "DELETE FROM weight_loss_profiles WHERE conversation_id = ?",
            (LEGACY_DEFAULT_SCOPE,),
        )
        conn.execute(
            "UPDATE weight_loss_meals SET conversation_id = ?, user_id = ? WHERE conversation_id = ? OR user_id IS NULL OR user_id = '' OR conversation_id NOT LIKE 'user:%'",
            (default_scope, DEFAULT_USER_ID, LEGACY_DEFAULT_SCOPE),
        )
        conn.execute(
            "UPDATE weight_loss_exercises SET conversation_id = ?, user_id = ? WHERE conversation_id = ? OR user_id IS NULL OR user_id = '' OR conversation_id NOT LIKE 'user:%'",
            (default_scope, DEFAULT_USER_ID, LEGACY_DEFAULT_SCOPE),
        )

    def get_profile(self, conversation_id: str, *, user_id: str | int | None = None) -> dict[str, Any]:
        self.ensure_schema()
        scope_id = self._scope_id(user_id)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM weight_loss_profiles WHERE conversation_id = ?",
                (scope_id,),
            ).fetchone()
        return dict(row) if row else {}

    def upsert_profile(self, conversation_id: str, updates: dict[str, Any], *, user_id: str | int | None = None) -> dict[str, Any]:
        normalized_user_id = self._normalize_user_id(user_id)
        scope_id = self._scope_id(normalized_user_id)
        allowed = {
            "daily_calorie_goal",
            "maintenance_calories",
            "target_deficit",
            "current_weight_kg",
            "target_weight_kg",
            "height_cm",
            "age_years",
            "sex",
            "activity_level",
            "notes",
        }
        cleaned = {key: value for key, value in updates.items() if key in allowed and value not in (None, "")}
        if not cleaned:
            return self.get_profile(conversation_id, user_id=normalized_user_id)

        self.ensure_schema()
        now = _iso()
        existing = self.get_profile(conversation_id, user_id=normalized_user_id)
        merged = {**existing, **cleaned}
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO weight_loss_profiles (
                    conversation_id, user_id, daily_calorie_goal, maintenance_calories, target_deficit,
                    current_weight_kg, target_weight_kg, height_cm, age_years, sex, activity_level,
                    notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    daily_calorie_goal = excluded.daily_calorie_goal,
                    maintenance_calories = excluded.maintenance_calories,
                    target_deficit = excluded.target_deficit,
                    current_weight_kg = excluded.current_weight_kg,
                    target_weight_kg = excluded.target_weight_kg,
                    height_cm = excluded.height_cm,
                    age_years = excluded.age_years,
                    sex = excluded.sex,
                    activity_level = excluded.activity_level,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (
                    scope_id,
                    normalized_user_id,
                    merged.get("daily_calorie_goal"),
                    merged.get("maintenance_calories"),
                    merged.get("target_deficit"),
                    merged.get("current_weight_kg"),
                    merged.get("target_weight_kg"),
                    merged.get("height_cm"),
                    merged.get("age_years"),
                    merged.get("sex"),
                    merged.get("activity_level"),
                    merged.get("notes"),
                    existing.get("created_at") or now,
                    now,
                ),
            )
        return self.get_profile(conversation_id, user_id=normalized_user_id)

    def add_meal(self, conversation_id: str, meal: dict[str, Any], *, user_id: str | int | None = None) -> dict[str, Any]:
        self.ensure_schema()
        normalized_user_id = self._normalize_user_id(user_id)
        scope_id = self._scope_id(normalized_user_id)
        meal_id = str(meal.get("id") or f"meal_{uuid4().hex}")
        logged_at = str(meal.get("logged_at") or _iso())
        total_calories = max(0, int(round(float(meal.get("total_calories") or 0))))
        row = {
            "id": meal_id,
            "conversation_id": scope_id,
            "user_id": normalized_user_id,
            "logged_at": logged_at,
            "meal_name": str(meal.get("meal_name") or "未命名餐食").strip(),
            "meal_type": str(meal.get("meal_type") or "unknown").strip(),
            "total_calories": total_calories,
            "calorie_min": _optional_int(meal.get("calorie_min")),
            "calorie_max": _optional_int(meal.get("calorie_max")),
            "protein_g": _optional_float(meal.get("protein_g")),
            "carbs_g": _optional_float(meal.get("carbs_g")),
            "fat_g": _optional_float(meal.get("fat_g")),
            "confidence": _optional_float(meal.get("confidence")),
            "source": str(meal.get("source") or "weight_loss_agent").strip(),
            "notes": str(meal.get("notes") or "").strip(),
            "image_count": max(0, int(meal.get("image_count") or 0)),
            "raw_json": _json_dumps(meal.get("raw_json") or meal),
            "created_at": _iso(),
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO weight_loss_meals (
                    id, conversation_id, user_id, logged_at, meal_name, meal_type, total_calories,
                    calorie_min, calorie_max, protein_g, carbs_g, fat_g, confidence,
                    source, notes, image_count, raw_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(row.values()),
            )
        return row

    def add_exercise(self, conversation_id: str, exercise: dict[str, Any], *, user_id: str | int | None = None) -> dict[str, Any]:
        self.ensure_schema()
        normalized_user_id = self._normalize_user_id(user_id)
        scope_id = self._scope_id(normalized_user_id)
        exercise_id = str(exercise.get("id") or f"exercise_{uuid4().hex}")
        calories = max(0, int(round(float(exercise.get("calories_burned") or 0))))
        row = {
            "id": exercise_id,
            "conversation_id": scope_id,
            "user_id": normalized_user_id,
            "logged_at": str(exercise.get("logged_at") or _iso()),
            "activity": str(exercise.get("activity") or "运动").strip(),
            "calories_burned": calories,
            "duration_min": _optional_float(exercise.get("duration_min")),
            "notes": str(exercise.get("notes") or "").strip(),
            "raw_json": _json_dumps(exercise.get("raw_json") or exercise),
            "created_at": _iso(),
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO weight_loss_exercises (
                    id, conversation_id, user_id, logged_at, activity, calories_burned,
                    duration_min, notes, raw_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(row.values()),
            )
        return row

    def list_meals(self, conversation_id: str, *, days: int = 7, user_id: str | int | None = None) -> list[dict[str, Any]]:
        self.ensure_schema()
        scope_id = self._scope_id(user_id)
        since = (utc_now() - timedelta(days=max(1, days))).isoformat()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM weight_loss_meals
                WHERE conversation_id = ? AND logged_at >= ?
                ORDER BY logged_at DESC
                """,
                (scope_id, since),
            ).fetchall()
        return [_row_to_meal(row) for row in rows]

    def list_exercises(self, conversation_id: str, *, days: int = 7, user_id: str | int | None = None) -> list[dict[str, Any]]:
        self.ensure_schema()
        scope_id = self._scope_id(user_id)
        since = (utc_now() - timedelta(days=max(1, days))).isoformat()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM weight_loss_exercises
                WHERE conversation_id = ? AND logged_at >= ?
                ORDER BY logged_at DESC
                """,
                (scope_id, since),
            ).fetchall()
        return [_row_to_exercise(row) for row in rows]

    def delete_latest_entry(self, conversation_id: str, *, user_id: str | int | None = None) -> dict[str, Any] | None:
        self.ensure_schema()
        scope_id = self._scope_id(user_id)
        with self._lock, self._connect() as conn:
            meal_row = conn.execute(
                """
                SELECT * FROM weight_loss_meals
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (scope_id,),
            ).fetchone()
            exercise_row = conn.execute(
                """
                SELECT * FROM weight_loss_exercises
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (scope_id,),
            ).fetchone()

            candidates: list[tuple[str, sqlite3.Row]] = []
            if meal_row:
                candidates.append(("meal", meal_row))
            if exercise_row:
                candidates.append(("exercise", exercise_row))
            if not candidates:
                return None

            entry_type, row = max(candidates, key=lambda item: _parse_datetime(item[1]["created_at"]))
            table = "weight_loss_meals" if entry_type == "meal" else "weight_loss_exercises"
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (row["id"],))

        deleted = _row_to_meal(row) if entry_type == "meal" else _row_to_exercise(row)
        deleted["entry_type"] = entry_type
        return deleted

    def summary(self, conversation_id: str, *, days: int = 7, user_id: str | int | None = None) -> dict[str, Any]:
        self.ensure_schema()
        normalized_user_id = self._normalize_user_id(user_id)
        scope_id = self._scope_id(normalized_user_id)
        bounded_days = max(1, min(days, 90))
        since = (datetime.now(LOCAL_TZ).date() - timedelta(days=bounded_days - 1)).isoformat()
        profile = self.get_profile(conversation_id, user_id=normalized_user_id)
        with self._lock, self._connect() as conn:
            meal_rows = conn.execute(
                """
                SELECT * FROM weight_loss_meals
                WHERE conversation_id = ?
                ORDER BY logged_at ASC
                """,
                (scope_id,),
            ).fetchall()
            exercise_rows = conn.execute(
                """
                SELECT * FROM weight_loss_exercises
                WHERE conversation_id = ?
                ORDER BY logged_at ASC
                """,
                (scope_id,),
            ).fetchall()

        meals = [_row_to_meal(row) for row in meal_rows if _local_date(row["logged_at"]) >= since]
        exercises = [dict(row) for row in exercise_rows if _local_date(row["logged_at"]) >= since]
        day_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "date": "",
                "intake": 0,
                "exercise": 0,
                "meal_count": 0,
                "exercise_count": 0,
                "items": [],
                "deficit": None,
                "goal_gap": None,
            }
        )

        for meal in meals:
            date_key = _local_date(meal["logged_at"])
            stat = day_stats[date_key]
            stat["date"] = date_key
            stat["intake"] += meal["total_calories"]
            stat["meal_count"] += 1
            stat["items"].append(meal)

        for exercise in exercises:
            date_key = _local_date(exercise["logged_at"])
            stat = day_stats[date_key]
            stat["date"] = date_key
            stat["exercise"] += int(exercise["calories_burned"] or 0)
            stat["exercise_count"] += 1

        maintenance = _optional_int(profile.get("maintenance_calories"))
        goal = _optional_int(profile.get("daily_calorie_goal"))
        daily_target_deficit = _optional_int(profile.get("target_deficit"))
        for stat in day_stats.values():
            if maintenance is not None:
                stat["deficit"] = maintenance + stat["exercise"] - stat["intake"]
            if goal is not None:
                stat["goal_gap"] = goal - stat["intake"]

        days_sorted = sorted(day_stats.values(), key=lambda item: item["date"], reverse=True)
        total_intake = sum(day["intake"] for day in days_sorted)
        total_exercise = sum(day["exercise"] for day in days_sorted)
        total_deficit = sum(day["deficit"] or 0 for day in days_sorted) if maintenance is not None else None
        average_intake = round(total_intake / bounded_days) if bounded_days else 0
        latest_meals = sorted(meals, key=lambda item: item["logged_at"], reverse=True)[:5]

        return {
            "conversation_id": conversation_id,
            "user_id": normalized_user_id,
            "scope_id": scope_id,
            "period_days": bounded_days,
            "profile": profile,
            "totals": {
                "intake": total_intake,
                "exercise": total_exercise,
                "deficit": total_deficit,
                "average_intake": average_intake,
                "meal_count": len(meals),
                "exercise_count": len(exercises),
                "target_deficit": daily_target_deficit,
            },
            "days": days_sorted,
            "latest_meals": latest_meals,
        }


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _row_to_meal(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["raw_json"] = _json_loads(result.get("raw_json"), {})
    return result


def _row_to_exercise(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["raw_json"] = _json_loads(result.get("raw_json"), {})
    return result
