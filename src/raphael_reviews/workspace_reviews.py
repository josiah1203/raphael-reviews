"""Derive open review state from workspace branch divergence."""

from __future__ import annotations

import os
from typing import Any

import httpx


def _workspaces_url() -> str:
    return os.environ.get("RAPHAEL_WORKSPACES_URL", "http://127.0.0.1:8083")


def _branch_commits(client: httpx.Client, workspace_id: str, module_id: str, branch: str) -> list[dict[str, Any]]:
    res = client.get(
        f"{_workspaces_url()}/v1/workspaces/{workspace_id}/modules/{module_id}/log",
        params={"branch": branch},
    )
    if res.status_code != 200:
        return []
    return res.json().get("commits", [])


def derive_workspace_reviews(stored: list[dict[str, Any]], workspace_id: str = "default") -> list[dict[str, Any]]:
    """Return synthetic open reviews for feature branches not already tracked."""
    stored_keys = {
        (r.get("workspace_id", workspace_id), r["module_id"], r["source_branch"])
        for r in stored
        if r.get("status") == "open"
    }
    derived: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=5.0) as client:
            mods_res = client.get(f"{_workspaces_url()}/v1/workspaces/{workspace_id}/modules")
            if mods_res.status_code != 200:
                return []
            modules = mods_res.json().get("modules") or mods_res.json().get("repos") or []
            for mod in modules:
                module_id = mod["id"]
                branches_res = client.get(
                    f"{_workspaces_url()}/v1/workspaces/{workspace_id}/modules/{module_id}/branches",
                )
                if branches_res.status_code != 200:
                    continue
                branches = branches_res.json().get("branches", [])
                main_hash = next(
                    (b.get("commit_hash") for b in branches if isinstance(b, dict) and b.get("name") == "main"),
                    None,
                )
                for branch in branches:
                    name = branch.get("name") if isinstance(branch, dict) else str(branch)
                    if name in ("main", "master"):
                        continue
                    key = (workspace_id, module_id, name)
                    if key in stored_keys:
                        continue
                    head = branch.get("commit_hash") if isinstance(branch, dict) else None
                    if main_hash and head == main_hash:
                        continue
                    commits = _branch_commits(client, workspace_id, module_id, name)
                    if not commits:
                        continue
                    derived.append(
                        {
                            "id": f"ws-{module_id}-{name}",
                            "repo_id": module_id,
                            "module_id": module_id,
                            "title": f"{name} → main",
                            "source_branch": name,
                            "target_branch": "main",
                            "status": "open",
                            "assignee": None,
                            "summary": f"{len(commits)} commit(s) on {name}",
                            "workspace_id": workspace_id,
                            "created_at": commits[0].get("timestamp") or commits[0].get("created_at") or "",
                            "derived": True,
                        }
                    )
    except httpx.RequestError:
        pass
    return derived
