"""SQLite:存每份报价的合计、疑点数与明细,便于同一户型多份报价对比。"""

from __future__ import annotations

import json
import os
import sqlite3
import threading

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "hejia.db")


class Database:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("HEJIA_DB") or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quotes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city TEXT, area REAL, total REAL, lines INTEGER,
                    issues INTEGER, detail TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
                """
            )
            self.conn.commit()

    def save(self, result: dict) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO quotes (city, area, total, lines, issues, detail) VALUES (?,?,?,?,?,?)",
                (result.get("city"), result.get("area"), result["summary"]["total"],
                 len([x for x in result["lines"] if x["ok"]]), len(result["issues"]),
                 json.dumps(result, ensure_ascii=False)),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def latest(self, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, city, area, total, lines, issues, created_at "
                "FROM quotes ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()
