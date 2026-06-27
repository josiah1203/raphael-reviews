"""Reviews API — /v1/reviews/*."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from raphael_reviews.diff import review_diff_from_commits
from raphael_reviews.sonoma_store import SonomaApiStore
from raphael_reviews.workspace_reviews import derive_workspace_reviews

router = APIRouter(tags=["reviews"])
_store = SonomaApiStore()
_comments_db = Path(os.environ.get("RAPHAEL_REVIEWS_DB", "/tmp/raphael-reviews-comments.db"))
_conn = sqlite3.connect(_comments_db, check_same_thread=False)
_conn.execute(
    """CREATE TABLE IF NOT EXISTS comments (
        id TEXT PRIMARY KEY,
        review_id TEXT NOT NULL,
        author TEXT,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL
    )"""
)
_conn.commit()


def _publish_event(event_type: str, data: dict[str, Any], workspace_id: str = "default") -> None:
    """Publish to Kafka; HTTP fallback for dev without Kafka."""
    try:
        from raphael_contracts.kafka import publish_event

        publish_event(event_type, data, source="raphael-reviews", workspace_id=workspace_id)
    except Exception:
        pass
    notif_url = os.environ.get("RAPHAEL_NOTIFICATIONS_URL", "http://127.0.0.1:8090")
    try:
        with httpx.Client(timeout=5.0) as client:
            client.post(f"{notif_url}/v1/notifications/events", json={"type": event_type, "data": data})
    except httpx.RequestError:
        pass


def _workspace_branches(workspace_id: str, module_id: str) -> list[str]:
    ws_url = os.environ.get("RAPHAEL_WORKSPACES_URL", "http://127.0.0.1:8083")
    try:
        with httpx.Client(timeout=5.0) as client:
            res = client.get(f"{ws_url}/v1/workspaces/{workspace_id}/modules/{module_id}/branches")
            if res.status_code == 200:
                return [b.get("name", b) if isinstance(b, dict) else str(b) for b in res.json().get("branches", [])]
    except httpx.RequestError:
        pass
    return []


def _resolve_branches(
    workspace_id: str,
    module_id: str,
    source_branch: str,
    target_branch: str,
) -> tuple[str, str]:
    """Derive branch names from workspace when only one side is specified."""
    branches = _workspace_branches(workspace_id, module_id)
    if not branches:
        return source_branch, target_branch
    if source_branch not in branches and len(branches) > 1:
        non_main = [b for b in branches if b != target_branch]
        if non_main:
            source_branch = non_main[0]
    if target_branch not in branches and "main" in branches:
        target_branch = "main"
    return source_branch, target_branch


def _fetch_branch_commits(workspace_id: str, module_id: str, branch: str) -> list[dict[str, Any]]:
    ws_url = os.environ.get("RAPHAEL_WORKSPACES_URL", "http://127.0.0.1:8083")
    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(
                f"{ws_url}/v1/workspaces/{workspace_id}/modules/{module_id}/log",
                params={"branch": branch},
            )
            if res.status_code == 200:
                return res.json().get("commits", [])
    except httpx.RequestError:
        pass
    return []


@router.get("")
def list_reviews(status: str | None = None) -> dict[str, list]:
    stored = _store.list_reviews(status)
    if status and status != "open":
        return {"reviews": stored}
    open_stored = [r for r in stored if r.get("status") == "open"]
    derived = derive_workspace_reviews(open_stored if status is None else stored)
    if status == "open":
        stored_ids = {r["id"] for r in stored}
        derived = [r for r in derived if r["id"] not in stored_ids]
        return {"reviews": stored + derived}
    merged = {r["id"]: r for r in stored}
    for item in derived:
        merged.setdefault(item["id"], item)
    return {"reviews": list(merged.values())}


@router.get("/{review_id}")
def get_review(review_id: str) -> dict[str, Any]:
    review = _store.get_review(review_id)
    if not review:
        for item in derive_workspace_reviews(_store.list_reviews("open")):
            if item["id"] == review_id:
                return item
        raise HTTPException(404, detail="not_found")
    return review


@router.post("")
def create_review(body: dict[str, Any]) -> dict[str, Any]:
    module_id = body.get("module_id") or body.get("repo_id", "")
    workspace_id = body.get("workspace_id", "default")
    source_branch = body["source_branch"]
    target_branch = body.get("target_branch", "main")
    source_branch, target_branch = _resolve_branches(workspace_id, module_id, source_branch, target_branch)
    review = _store.create_review(
        repo_id=module_id,
        title=body["title"],
        source_branch=source_branch,
        target_branch=target_branch,
        assignee=body.get("assignee"),
        summary=body.get("summary"),
        workspace_id=workspace_id,
    )
    _publish_event("raphael.reviews.created", review, workspace_id)
    return review


@router.get("/{review_id}/diff")
def review_diff(review_id: str) -> dict[str, Any]:
    review = _store.get_review(review_id)
    if not review:
        review = next((r for r in derive_workspace_reviews([]) if r["id"] == review_id), None)
    if not review:
        raise HTTPException(404, detail="not_found")
    module_id = review["module_id"]
    workspace_id = review.get("workspace_id", "default")
    source_branch = review["source_branch"]
    target_branch = review.get("target_branch", "main")
    source_commits = _fetch_branch_commits(workspace_id, module_id, source_branch)
    target_commits = _fetch_branch_commits(workspace_id, module_id, target_branch)
    target_hashes = {c.get("hash") for c in target_commits if c.get("hash")}
    unique_source = [c for c in source_commits if c.get("hash") not in target_hashes]
    return review_diff_from_commits(unique_source or source_commits, [])


@router.post("/{review_id}/merge")
def merge_review(review_id: str) -> dict[str, Any]:
    review = _store.get_review(review_id)
    if not review:
        review = next((r for r in derive_workspace_reviews([]) if r["id"] == review_id), None)
    if not review:
        raise HTTPException(404, detail="not_found")
    ws_url = os.environ.get("RAPHAEL_WORKSPACES_URL", "http://127.0.0.1:8083")
    module_id = review["module_id"]
    workspace_id = review.get("workspace_id", "default")
    with httpx.Client(timeout=30.0) as client:
        res = client.post(
            f"{ws_url}/v1/workspaces/{workspace_id}/modules/{module_id}/merge",
            json={"source": review["source_branch"], "target": review["target_branch"]},
        )
        result = res.json() if res.status_code < 400 else {"status": "error", "error": res.text}
    if _store.get_review(review_id):
        _store.update_review_status(review_id, "merged")
    _publish_event("raphael.reviews.merged", {"review_id": review_id, **result}, workspace_id)
    return result


@router.get("/{review_id}/comments")
def list_comments(review_id: str) -> dict[str, list]:
    rows = _conn.execute(
        "SELECT id, review_id, author, body, created_at FROM comments WHERE review_id = ? ORDER BY created_at",
        (review_id,),
    ).fetchall()
    return {
        "comments": [
            {"id": r[0], "review_id": r[1], "author": r[2], "body": r[3], "created_at": r[4]} for r in rows
        ]
    }


@router.post("/{review_id}/comments")
def add_comment(review_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not _store.get_review(review_id):
        raise HTTPException(404, detail="not_found")
    cid = f"cmt-{int(datetime.now(timezone.utc).timestamp())}"
    now = datetime.now(timezone.utc).isoformat()
    _conn.execute(
        "INSERT INTO comments (id, review_id, author, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (cid, review_id, body.get("author", "user"), body["body"], now),
    )
    _conn.commit()
    return {"id": cid, "review_id": review_id, "author": body.get("author", "user"), "body": body["body"], "created_at": now}
