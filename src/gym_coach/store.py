"""SQLite record storage for plans, logged sets, meals, body numbers, API calls, kv."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_sessions (
    date TEXT PRIMARY KEY, gym TEXT NOT NULL, kind TEXT NOT NULL
        CHECK (kind IN ('strength','cardio')),
    status TEXT NOT NULL CHECK (status IN ('proposed','approved','done','skipped')),
    exercises TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS logged_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, exercise TEXT NOT NULL,
    set_no INTEGER NOT NULL, weight_kg REAL, reps INTEGER, effort TEXT);
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
    description TEXT NOT NULL, kcal REAL NOT NULL, protein_g REAL NOT NULL);
CREATE TABLE IF NOT EXISTS body (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, weight_kg REAL, waist_cm REAL);
CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def _run(self, sql: str, args: tuple = ()) -> None:
        with self._db:
            self._db.execute(sql, args)

    # plan sessions
    def add_plan_session(self, date, gym, kind, status, exercises) -> None:
        self._run(
            "INSERT OR REPLACE INTO plan_sessions VALUES (?,?,?,?,?)",
            (date, gym, kind, status, json.dumps(exercises)),
        )

    def _plan(self, row: dict) -> dict:
        row["exercises"] = json.loads(row["exercises"])
        return row

    def plan_session(self, date) -> dict | None:
        rows = self._rows("SELECT * FROM plan_sessions WHERE date=?", (date,))
        return self._plan(rows[0]) if rows else None

    def plan_sessions(self, start, end) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM plan_sessions WHERE date BETWEEN ? AND ? ORDER BY date",
            (start, end),
        )
        return [self._plan(r) for r in rows]

    def delete_plan_session(self, date) -> None:
        self._run("DELETE FROM plan_sessions WHERE date=?", (date,))

    def set_plan_status(self, date, status) -> None:
        self._run("UPDATE plan_sessions SET status=? WHERE date=?", (status, date))

    # logged sets
    def add_logged_set(self, date, exercise, set_no, weight_kg, reps, effort=None) -> None:
        self._run(
            "INSERT INTO logged_sets (date, exercise, set_no, weight_kg, reps, effort)"
            " VALUES (?,?,?,?,?,?)",
            (date, exercise, set_no, weight_kg, reps, effort),
        )

    def logged_sets(self, date) -> list[dict]:
        return self._rows("SELECT * FROM logged_sets WHERE date=? ORDER BY id", (date,))

    def clear_logged_sets(self, date) -> None:
        self._run("DELETE FROM logged_sets WHERE date=?", (date,))

    # meals
    def add_meal(self, timestamp, description, kcal, protein_g) -> None:
        self._run(
            "INSERT INTO meals (timestamp, description, kcal, protein_g) VALUES (?,?,?,?)",
            (timestamp, description, kcal, protein_g),
        )

    def meals_on(self, date) -> list[dict]:
        return self._rows(
            "SELECT * FROM meals WHERE substr(timestamp,1,10)=? ORDER BY timestamp", (date,)
        )

    # body
    def add_body(self, date, weight_kg, waist_cm) -> None:
        self._run(
            "INSERT INTO body (date, weight_kg, waist_cm) VALUES (?,?,?)",
            (date, weight_kg, waist_cm),
        )

    def body_entries(self) -> list[dict]:
        return self._rows("SELECT * FROM body ORDER BY date, id")

    # api calls
    def add_api_call(self, timestamp, model, input_tokens, output_tokens, cost_usd) -> None:
        self._run(
            "INSERT INTO api_calls (timestamp, model, input_tokens, output_tokens, cost_usd)"
            " VALUES (?,?,?,?,?)",
            (timestamp, model, input_tokens, output_tokens, cost_usd),
        )

    def cost_between(self, start, end) -> float:
        """Total cost for timestamps >= start and < end (ISO strings)."""
        row = self._db.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM api_calls WHERE timestamp>=? AND timestamp<?",
            (start, end),
        ).fetchone()
        return float(row[0])

    # kv
    def get(self, key, default=None):
        row = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key, value) -> None:
        self._run("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, str(value)))
