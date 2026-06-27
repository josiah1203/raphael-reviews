"""Reviews API tests."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from raphael_reviews.app import app

client = TestClient(app)


def test_list_reviews_empty_by_default() -> None:
    res = client.get("/v1/reviews")
    assert res.status_code == 200
    assert isinstance(res.json()["reviews"], list)


def test_get_review_not_found() -> None:
    res = client.get("/v1/reviews/rev-does-not-exist")
    assert res.status_code == 404


def test_create_review_and_get() -> None:
    res = client.post(
        "/v1/reviews",
        json={
            "module_id": "test-module",
            "title": "Test review",
            "source_branch": "feature/test",
            "target_branch": "main",
        },
    )
    assert res.status_code == 200
    review = res.json()
    assert review["module_id"] == "test-module"
    assert review["status"] == "open"
    fetched = client.get(f"/v1/reviews/{review['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Test review"


def test_create_review_publishes_kafka(monkeypatch) -> None:
    published: list[tuple] = []
    monkeypatch.setattr("raphael_contracts.kafka.publish_event", lambda t, d, **m: published.append((t, d)))
    res = client.post(
        "/v1/reviews",
        json={
            "module_id": "kafka-module",
            "title": "Kafka review",
            "source_branch": "feature/kafka",
            "target_branch": "main",
        },
    )
    assert res.status_code == 200
    assert any(p[0] == "raphael.reviews.created" for p in published)


def test_review_diff_shape() -> None:
    created = client.post(
        "/v1/reviews",
        json={
            "module_id": "power-board-v2",
            "title": "Diff test",
            "source_branch": "feature/usb-pd-input",
            "target_branch": "main",
        },
    ).json()
    diff = client.get(f"/v1/reviews/{created['id']}/diff")
    assert diff.status_code == 200
    body = diff.json()
    assert "bom" in body and "summary" in body


def test_review_comments() -> None:
    created = client.post(
        "/v1/reviews",
        json={
            "module_id": "test-module",
            "title": "Comment test",
            "source_branch": "feature/comments",
        },
    ).json()
    rid = created["id"]
    post = client.post(f"/v1/reviews/{rid}/comments", json={"author": "tester", "body": "Looks good"})
    assert post.status_code == 200
    comments = client.get(f"/v1/reviews/{rid}/comments").json()["comments"]
    assert any(c["body"] == "Looks good" for c in comments)


@patch("raphael_reviews.routes.httpx.Client")
def test_merge_review_delegates_to_workspaces(mock_client_cls) -> None:
    created = client.post(
        "/v1/reviews",
        json={
            "module_id": "power-board-v2",
            "title": "Merge test",
            "source_branch": "feature/merge",
            "target_branch": "main",
        },
    ).json()
    mock_client = mock_client_cls.return_value.__enter__.return_value
    mock_client.post.return_value.status_code = 200
    mock_client.post.return_value.json.return_value = {"status": "merged", "commit_hash": "abc123"}
    res = client.post(f"/v1/reviews/{created['id']}/merge")
    assert res.status_code == 200
    assert res.json()["status"] == "merged"
    updated = client.get(f"/v1/reviews/{created['id']}").json()
    assert updated["status"] == "merged"


@patch("raphael_reviews.workspace_reviews.httpx.Client")
def test_derived_workspace_reviews(mock_client_cls) -> None:
    mock_client = mock_client_cls.return_value.__enter__.return_value
    mock_client.get.side_effect = [
        _mock_response(
            200,
            {"modules": [{"id": "power-board-v2", "name": "Power Board"}]},
        ),
        _mock_response(200, {"branches": [{"name": "main", "commit_hash": "aaa"}, {"name": "feature/x", "commit_hash": "bbb"}]}),
        _mock_response(200, {"commits": [{"hash": "bbb", "message": "Feature work", "timestamp": "2026-01-01T00:00:00Z"}]}),
    ]
    res = client.get("/v1/reviews?status=open")
    assert res.status_code == 200
    reviews = res.json()["reviews"]
    assert any(r.get("derived") and r["source_branch"] == "feature/x" for r in reviews)


def _mock_response(code: int, payload: dict):
    class _Res:
        status_code = code

        @staticmethod
        def json():
            return payload

    return _Res()


def test_seeded_reviews_when_env_set(monkeypatch) -> None:
    monkeypatch.setenv("RAPHAEL_REVIEWS_SEED", "1")
    monkeypatch.setenv("RAPHAEL_REVIEWS_DB", "/tmp/raphael-reviews-seed-test.db")
    from raphael_reviews.sonoma_store import SonomaApiStore

    store = SonomaApiStore()
    reviews = store.list_reviews()
    assert any(r["id"] == "pr-42" for r in reviews)
