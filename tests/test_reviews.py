"""Reviews API tests."""

from fastapi.testclient import TestClient

from raphael_reviews.app import app

client = TestClient(app)


def test_list_reviews_seeded() -> None:
    res = client.get("/v1/reviews")
    assert res.status_code == 200
    assert len(res.json()["reviews"]) >= 1


def test_review_diff() -> None:
    reviews = client.get("/v1/reviews").json()["reviews"]
    rid = reviews[0]["id"]
    diff = client.get(f"/v1/reviews/{rid}/diff")
    assert diff.status_code == 200
    body = diff.json()
    assert "bom" in body and "summary" in body
