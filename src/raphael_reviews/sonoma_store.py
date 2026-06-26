"""Trimmed SonomaApiStore copy for review workflows."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SonomaApiStore:
    def __init__(self, db_path: Path | None = None):
        default_db = Path(os.environ.get("RAPHAEL_REVIEWS_DB", "/tmp/raphael-reviews.db"))
        self.db_path = db_path or default_db
        self._init_db()
        self._seed_defaults()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reviews (
                    id TEXT PRIMARY KEY,
                    repo_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_branch TEXT NOT NULL,
                    target_branch TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    assignee TEXT,
                    summary TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _seed_defaults(self) -> None:
        with self._conn() as conn:
            review_count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
            if review_count == 0:
                now = _utc_now()
                conn.executemany(
                    """
                    INSERT INTO reviews (id, repo_id, title, source_branch, target_branch, status, assignee, summary, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "pr-42",
                            "power-board-v2",
                            "USB-PD input stage",
                            "feature/usb-pd-input",
                            "main",
                            "open",
                            "Alex Chen",
                            "14 components affected, 3 new nets, 2 DRC warnings",
                            now,
                        ),
                        (
                            "pr-39",
                            "power-board-v2",
                            "Stackup update 4-layer",
                            "review/v2.3-fab-release",
                            "main",
                            "open",
                            "Sam Rivera",
                            "2 layer changes, 0 DRC warnings",
                            now,
                        ),
                    ],
                )

    def list_reviews(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT id, repo_id, title, source_branch, target_branch, status, assignee, summary, created_at FROM reviews WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, repo_id, title, source_branch, target_branch, status, assignee, summary, created_at FROM reviews ORDER BY created_at DESC"
                ).fetchall()
        return [
            {
                "id": r[0],
                "repo_id": r[1],
                "module_id": r[1],
                "title": r[2],
                "source_branch": r[3],
                "target_branch": r[4],
                "status": r[5],
                "assignee": r[6],
                "summary": r[7],
                "created_at": r[8],
            }
            for r in rows
        ]

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        reviews = self.list_reviews()
        return next((r for r in reviews if r["id"] == review_id), None)

    def create_review(
        self,
        repo_id: str,
        title: str,
        source_branch: str,
        target_branch: str = "main",
        assignee: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        review_id = f"pr-{int(datetime.now(timezone.utc).timestamp())}"
        now = _utc_now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO reviews (id, repo_id, title, source_branch, target_branch, status, assignee, summary, created_at)
                VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (review_id, repo_id, title, source_branch, target_branch, assignee, summary or "", now),
            )
        return self.get_review(review_id) or {}

    def update_review_status(self, review_id: str, status: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            conn.execute("UPDATE reviews SET status = ? WHERE id = ?", (status, review_id))
        return self.get_review(review_id)
