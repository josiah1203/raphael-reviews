"""Reviews API — /v1/reviews/*."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from raphael_reviews.diff import review_diff_from_commits
from raphael_reviews.sonoma_store import SonomaApiStore

router = APIRouter(tags=["reviews"])
_store = SonomaApiStore()


def _publish_event(event_type: str, data: dict[str, Any]) -> None:
    envelope = {"type": event_type, "data": data}
    notif_url = os.environ.get("RAPHAEL_NOTIFICATIONS_URL", "http://127.0.0.1:8090")
    try:
        with httpx.Client(timeout=5.0) as client:
            client.post(f"{notif_url}/v1/notifications/events", json=envelope)
    except httpx.RequestError:
        pass  # ponytail: non-blocking; Kafka consumer is production path


@router.get("")
def list_reviews(status: str | None = None) -> dict[str, list]:
    return {"reviews": _store.list_reviews(status)}


@router.get("/{review_id}")
def get_review(review_id: str) -> dict[str, Any]:
    review = _store.get_review(review_id)
    if not review:
        raise HTTPException(404, detail="not_found")
    return review


@router.post("")
def create_review(body: dict[str, Any]) -> dict[str, Any]:
    module_id = body.get("module_id") or body.get("repo_id", "")
    review = _store.create_review(
        repo_id=module_id,
        title=body["title"],
        source_branch=body["source_branch"],
        target_branch=body.get("target_branch", "main"),
        assignee=body.get("assignee"),
        summary=body.get("summary"),
    )
    _publish_event("raphael.reviews.created", review)
    return review


@router.get("/{review_id}/diff")
def review_diff(review_id: str) -> dict[str, Any]:
    review = _store.get_review(review_id)
    if not review:
        raise HTTPException(404, detail="not_found")
    ws_url = os.environ.get("RAPHAEL_WORKSPACES_URL", "http://127.0.0.1:8083")
    module_id = review["module_id"]
    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(f"{ws_url}/v1/workspaces/default/modules/{module_id}/log")
            commits = res.json().get("commits", []) if res.status_code == 200 else []
    except httpx.RequestError:
        commits = []
    return review_diff_from_commits(commits, [])


@router.post("/{review_id}/merge")
def merge_review(review_id: str) -> dict[str, Any]:
    review = _store.get_review(review_id)
    if not review:
        raise HTTPException(404, detail="not_found")
    ws_url = os.environ.get("RAPHAEL_WORKSPACES_URL", "http://127.0.0.1:8083")
    module_id = review["module_id"]
    with httpx.Client(timeout=30.0) as client:
        res = client.post(
            f"{ws_url}/v1/workspaces/default/modules/{module_id}/merge",
            json={"source": review["source_branch"], "target": review["target_branch"]},
        )
        result = res.json() if res.status_code < 400 else {"status": "error", "error": res.text}
    _store.update_review_status(review_id, "merged")
    _publish_event("raphael.reviews.merged", {"review_id": review_id, **result})
    return result
