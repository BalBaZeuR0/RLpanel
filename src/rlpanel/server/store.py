"""SQLite erişim katmanı.

HTTP ya da dosya biçimi bilmez; yalnız proje/run/metrik/log saklar.
Tek bağlantı + RLock: tüm metotlar thread-safe.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence

from rlpanel.jsonutil import clean_json

SCHEMA = """
CREATE TABLE IF NOT EXISTS project(
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS run(
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- silinen run'ın id'si (ve linki) başka run'a geçmesin
    project_id INTEGER NOT NULL REFERENCES project(id),
    name TEXT NOT NULL,
    seed INTEGER,
    status TEXT NOT NULL DEFAULT 'running',
    source TEXT NOT NULL DEFAULT 'client',
    host TEXT,
    config TEXT,
    results TEXT,
    total_steps INTEGER,
    current_step INTEGER,
    started_at REAL NOT NULL,
    ended_at REAL,
    last_heartbeat REAL,
    content_hash TEXT
);
CREATE TABLE IF NOT EXISTS metric(
    run_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    step INTEGER NOT NULL,
    value REAL NOT NULL,
    wall_time REAL
);
CREATE INDEX IF NOT EXISTS metric_idx ON metric(run_id, key, step);
CREATE TABLE IF NOT EXISTS log(
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    wall_time REAL,
    level TEXT,
    line TEXT
);
CREATE INDEX IF NOT EXISTS log_idx ON log(run_id, id);
CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

REWARD_KEYS = ("rollout/ep_rew_mean", "eval/mean_reward", "reward", "ep_reward", "episode_reward")

_RUN_FIELDS = {"name", "seed", "status", "host", "config", "results", "total_steps",
               "current_step", "ended_at", "last_heartbeat", "content_hash"}
_JSON_FIELDS = {"config", "results"}
_RUN_SELECT = "SELECT run.*, project.name AS project FROM run JOIN project ON project.id = run.project_id"


def _dump(value: Any) -> str | None:
    return None if value is None else json.dumps(clean_json(value), ensure_ascii=False, default=str)


def _run_dict(row: sqlite3.Row) -> dict:
    run = dict(row)
    for key in _JSON_FIELDS:
        run[key] = json.loads(run[key]) if run[key] else None
    return run


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('instance_id', ?)", (uuid.uuid4().hex,))
        self._db.commit()
        # İstemciler bununla veritabanının değiştiğini anlar: eski run id'leri başka run'a yazmasın.
        self.instance_id = self._db.execute("SELECT value FROM meta WHERE key = 'instance_id'").fetchone()["value"]

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _read(self, sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def _write(self, sql: str, params: Sequence = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._db.execute(sql, params)
            self._db.commit()
            return cursor

    # ---- projeler ----
    def get_or_create_project(self, name: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT id FROM project WHERE name = ?", (name,)).fetchone()
            if row:
                return row["id"]
            return self._write("INSERT INTO project(name, created_at) VALUES (?, ?)", (name, time.time())).lastrowid

    # ---- run'lar ----
    def create_run(self, project: str, name: str, *, seed: int | None = None, source: str = "client",
                   host: str | None = None, config: Any = None, total_steps: int | None = None,
                   content_hash: str | None = None, status: str = "running") -> int:
        project_id = self.get_or_create_project(project)
        now = time.time()
        return self._write(
            "INSERT INTO run(project_id, name, seed, status, source, host, config, total_steps, current_step,"
            " started_at, last_heartbeat, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, name, seed, status, source, host, _dump(config), total_steps, 0, now, now, content_hash),
        ).lastrowid

    def update_run(self, run_id: int, **fields: Any) -> None:
        unknown = set(fields) - _RUN_FIELDS
        if unknown:
            raise ValueError(f"bilinmeyen run alanı: {sorted(unknown)}")
        if not fields:
            return
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = [_dump(value) if key in _JSON_FIELDS else value for key, value in fields.items()]
        self._write(f"UPDATE run SET {columns} WHERE id = ?", (*values, run_id))

    def get_run(self, run_id: int) -> dict | None:
        rows = self._read(_RUN_SELECT + " WHERE run.id = ?", (run_id,))
        return _run_dict(rows[0]) if rows else None

    def find_run(self, project: str, name: str, source: str) -> int | None:
        rows = self._read(
            "SELECT run.id FROM run JOIN project ON project.id = run.project_id"
            " WHERE project.name = ? AND run.name = ? AND run.source = ? ORDER BY run.id DESC LIMIT 1",
            (project, name, source),
        )
        return rows[0]["id"] if rows else None

    def find_run_by_hash(self, content_hash: str) -> int | None:
        rows = self._read("SELECT id FROM run WHERE content_hash = ? LIMIT 1", (content_hash,))
        return rows[0]["id"] if rows else None

    def list_runs(self, project: str | None = None) -> list[dict]:
        sql, params = _RUN_SELECT, ()
        if project:
            sql, params = sql + " WHERE project.name = ?", (project,)
        runs = [_run_dict(row) for row in self._read(sql + " ORDER BY run.started_at DESC, run.id DESC", params)]
        for run in runs:
            run.update(self.reward_summary(run["id"]))
        return runs

    def reward_summary(self, run_id: int, points: int = 60) -> dict:
        keys = set(self.metric_keys(run_id))
        key = next((k for k in REWARD_KEYS if k in keys), None)
        if key is None:
            return {"reward_key": None, "last_reward": None, "spark": []}
        values = [row["value"] for row in self._read(
            "SELECT value FROM metric WHERE run_id = ? AND key = ? ORDER BY step, rowid", (run_id, key))]
        if len(values) > points:
            indices = sorted({round(i * (len(values) - 1) / (points - 1)) for i in range(points)})
            spark = [values[i] for i in indices]
        else:
            spark = values
        return {"reward_key": key, "last_reward": values[-1] if values else None, "spark": spark}

    def delete_run(self, run_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM metric WHERE run_id = ?", (run_id,))
            self._db.execute("DELETE FROM log WHERE run_id = ?", (run_id,))
            self._db.execute("DELETE FROM run WHERE id = ?", (run_id,))
            self._db.commit()

    def mark_unresponsive(self, timeout: float, now: float | None = None) -> list[int]:
        cutoff = (time.time() if now is None else now) - timeout
        with self._lock:
            ids = [row["id"] for row in self._db.execute(
                "SELECT id FROM run WHERE status = 'running' AND last_heartbeat < ?", (cutoff,)).fetchall()]
            if ids:
                self._db.executemany("UPDATE run SET status = 'unresponsive' WHERE id = ?", [(i,) for i in ids])
                self._db.commit()
        return ids

    # ---- metrikler ----
    def add_metrics(self, run_id: int, rows: Iterable[Sequence]) -> list[list]:
        kept: list[list] = []
        for key, step, value, wall_time in rows:
            try:
                number, step_int = float(value), int(step)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                kept.append([str(key), step_int, number, None if wall_time is None else float(wall_time)])
        if kept:
            with self._lock:
                self._db.executemany(
                    "INSERT INTO metric(run_id, key, step, value, wall_time) VALUES (?, ?, ?, ?, ?)",
                    [(run_id, *row) for row in kept],
                )
                self._db.commit()
        return kept

    def clear_metrics(self, run_id: int) -> None:
        self._write("DELETE FROM metric WHERE run_id = ?", (run_id,))

    def metric_keys(self, run_id: int) -> list[str]:
        return [row["key"] for row in self._read(
            "SELECT DISTINCT key FROM metric WHERE run_id = ? ORDER BY key", (run_id,))]

    def get_metrics(self, run_id: int, keys: Sequence[str] | None = None) -> dict[str, list[list]]:
        sql, params = "SELECT key, step, value, wall_time FROM metric WHERE run_id = ?", [run_id]
        if keys:
            sql += f" AND key IN ({','.join('?' * len(keys))})"
            params += list(keys)
        out: dict[str, list[list]] = {}
        for row in self._read(sql + " ORDER BY key, step, rowid", params):
            out.setdefault(row["key"], []).append([row["step"], row["value"], row["wall_time"]])
        return out

    # ---- loglar ----
    def add_logs(self, run_id: int, rows: Iterable[Sequence]) -> list[dict]:
        out: list[dict] = []
        with self._lock:
            for wall_time, level, line in rows:
                cursor = self._db.execute(
                    "INSERT INTO log(run_id, wall_time, level, line) VALUES (?, ?, ?, ?)",
                    (run_id, wall_time, str(level), str(line)),
                )
                out.append({"id": cursor.lastrowid, "wall_time": wall_time, "level": str(level), "line": str(line)})
            self._db.commit()
        return out

    def get_logs(self, run_id: int, after_id: int = 0, tail: int | None = None) -> list[dict]:
        if tail:
            rows = self._read(
                "SELECT id, wall_time, level, line FROM log WHERE run_id = ? AND id > ? ORDER BY id DESC LIMIT ?",
                (run_id, after_id, tail),
            )
            return [dict(row) for row in reversed(rows)]
        rows = self._read(
            "SELECT id, wall_time, level, line FROM log WHERE run_id = ? AND id > ? ORDER BY id", (run_id, after_id))
        return [dict(row) for row in rows]
