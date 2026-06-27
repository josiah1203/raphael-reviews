"""Reviews store domain tests."""

from pathlib import Path

import pytest

from raphael_reviews.sonoma_store import SonomaApiStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SonomaApiStore:
    monkeypatch.delenv("RAPHAEL_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAPHAEL_REVIEWS_SEED", raising=False)
    return SonomaApiStore(db_path=tmp_path / "reviews.db")


def test_create_and_get_review(store: SonomaApiStore) -> None:
    created = store.create_review(
        repo_id="mod-1",
        title="Store test",
        source_branch="feature/x",
        target_branch="main",
    )
    assert created["status"] == "open"
    fetched = store.get_review(created["id"])
    assert fetched is not None
    assert fetched["title"] == "Store test"


def test_list_reviews_by_status(store: SonomaApiStore) -> None:
    store.create_review("mod-2", "Open review", "feature/a")
    store.create_review("mod-3", "Closed review", "feature/b")
    store.update_review_status(store.list_reviews()[0]["id"], "merged")
    open_reviews = store.list_reviews(status="open")
    merged = store.list_reviews(status="merged")
    assert len(open_reviews) >= 1
    assert len(merged) >= 1


def test_seeded_reviews_when_env_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAPHAEL_DATABASE_URL", raising=False)
    monkeypatch.setenv("RAPHAEL_REVIEWS_SEED", "1")
    store = SonomaApiStore(db_path=tmp_path / "reviews-seed.db")
    reviews = store.list_reviews()
    assert any(r["id"] == "pr-42" for r in reviews)


def test_reviews_persist_across_instances(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAPHAEL_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAPHAEL_REVIEWS_SEED", raising=False)
    db = tmp_path / "reviews-persist.db"
    store1 = SonomaApiStore(db_path=db)
    created = store1.create_review("mod-p", "Persist", "feature/p")
    store2 = SonomaApiStore(db_path=db)
    assert store2.get_review(created["id"]) is not None
