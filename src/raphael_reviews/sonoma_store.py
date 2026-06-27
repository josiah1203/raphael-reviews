"""Trimmed SonomaApiStore copy for review workflows."""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SonomaApiStore:
    def __init__(self, db_path: Path | None = None):
        from raphael_contracts import db as rdb

        self._postgres = rdb.is_postgres()
        if self._postgres:
            rdb.ensure_migrations()
            self.db_path = Path("postgres")
        else:
            default_db = Path(os.environ.get("RAPHAEL_REVIEWS_DB", "/tmp/raphael-reviews.db"))
            self.db_path = db_path or default_db
            self._init_sqlite()
        self._seed_defaults()

    def _connect_sqlite(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _init_sqlite(self) -> None:
        with self._connect_sqlite() as conn:
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
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    created_at TEXT NOT NULL
                )
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()}
            if "workspace_id" not in cols:
                conn.execute("ALTER TABLE reviews ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'")

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if self._postgres:
            from raphael_contracts.db import pg_execute

            pg_execute(sql, params)
            return
        with self._connect_sqlite() as conn:
            conn.execute(sql, params)
            conn.commit()

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        if self._postgres:
            from raphael_contracts.db import pg_fetchall

            return pg_fetchall(sql, params)
        with self._connect_sqlite() as conn:
            return conn.execute(sql, params).fetchall()

    def _seed_defaults(self) -> None:
        if os.environ.get("RAPHAEL_REVIEWS_SEED", "").lower() not in ("1", "true", "yes"):
            return
        row = self._fetchall("SELECT COUNT(*) AS cnt FROM reviews")
        review_count = row[0]["cnt"] if isinstance(row[0], dict) else row[0][0]
        if review_count == 0:
            now = _utc_now()
            self._execute(
                """
                INSERT INTO reviews (id, repo_id, title, source_branch, target_branch, status, assignee, summary, workspace_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """ if not self._postgres else """
                INSERT INTO reviews (id, repo_id, title, source_branch, target_branch, status, assignee, summary, workspace_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    "pr-42",
                    "power-board-v2",
                    "USB-PD input stage",
                    "feature/usb-pd-input",
                    "main",
                    "open",
                    "Alex Chen",
                    "14 components affected, 3 new nets, 2 DRC warnings",
                    "default",
                    now,
                ),
            )

    def list_reviews(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            if self._postgres:
                rows = self._fetchall(
                    """
                    SELECT id, repo_id, title, source_branch, target_branch, status, assignee, summary, workspace_id, created_at
                    FROM reviews WHERE status = %s ORDER BY created_at DESC
                    """,
                    (status,),
                )
            else:
                rows = self._fetchall(
                    """
                    SELECT id, repo_id, title, source_branch, target_branch, status, assignee, summary, workspace_id, created_at
                    FROM reviews WHERE status = ? ORDER BY created_at DESC
                    """,
                    (status,),
                )
        else:
            rows = self._fetchall(
                """
                SELECT id, repo_id, title, source_branch, target_branch, status, assignee, summary, workspace_id, created_at
                FROM reviews ORDER BY created_at DESC
                """
            )
        return [self._review_row(r) for r in rows]

    @staticmethod
    def _review_row(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            repo_id = row["repo_id"]
            return {
                "id": row["id"],
                "repo_id": repo_id,
                "module_id": repo_id,
                "title": row["title"],
                "source_branch": row["source_branch"],
                "target_branch": row["target_branch"],
                "status": row["status"],
                "assignee": row.get("assignee"),
                "summary": row.get("summary"),
                "workspace_id": row.get("workspace_id", "default"),
                "created_at": str(row.get("created_at") or ""),
            }
        return {
            "id": row[0],
            "repo_id": row[1],
            "module_id": row[1],
            "title": row[2],
            "source_branch": row[3],
            "target_branch": row[4],
            "status": row[5],
            "assignee": row[6],
            "summary": row[7],
            "workspace_id": row[8],
            "created_at": row[9],
        }

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
        workspace_id: str = "default",
    ) -> dict[str, Any]:
        review_id = f"pr-{uuid.uuid4().hex[:10]}"
        now = _utc_now()
        if self._postgres:
            self._execute(
                """
                INSERT INTO reviews (id, repo_id, title, source_branch, target_branch, status, assignee, summary, workspace_id, created_at)
                VALUES (%s, %s, %s, %s, %s, 'open', %s, %s, %s, %s)
                """,
                (review_id, repo_id, title, source_branch, target_branch, assignee, summary or "", workspace_id, now),
            )
        else:
            self._execute(
                """
                INSERT INTO reviews (id, repo_id, title, source_branch, target_branch, status, assignee, summary, workspace_id, created_at)
                VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
                """,
                (review_id, repo_id, title, source_branch, target_branch, assignee, summary or "", workspace_id, now),
            )
        return self.get_review(review_id) or {}

    def update_review_status(self, review_id: str, status: str) -> dict[str, Any] | None:
        if self._postgres:
            self._execute("UPDATE reviews SET status = %s WHERE id = %s", (status, review_id))
        else:
            self._execute("UPDATE reviews SET status = ? WHERE id = ?", (status, review_id))
        return self.get_review(review_id)
