"""Review diff builder — ported from calliope sonoma_api."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def list_branches(vcs_storage: Any, repo_id: str) -> list[dict[str, Any]]:
    if hasattr(vcs_storage, "list_branches"):
        return vcs_storage.list_branches(repo_id)
    with sqlite3.connect(vcs_storage.db_path) as conn:
        rows = conn.execute(
            "SELECT name, commit_hash FROM refs WHERE repo_id = ? ORDER BY name",
            (repo_id,),
        ).fetchall()
    return [{"name": r[0], "commit_hash": r[1]} for r in rows]


def adapter_status_from_events(
    events: list[dict[str, Any]],
    connections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    by_tool: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for event in events:
        source = event.get("source") or {}
        tool = source.get("tool") or source.get("adapter") or event.get("tool") or "unknown"
        if tool == "unknown":
            continue
        project = event.get("project_id") or "default"
        ts = event.get("timestamp_utc") or event.get("created_at") or ""
        entry = by_tool.setdefault(
            tool,
            {"tool": tool, "last_event_at": ts, "repos": set(), "event_count": 0},
        )
        entry["event_count"] += 1
        entry["repos"].add(project)
        if ts > entry["last_event_at"]:
            entry["last_event_at"] = ts

    available = [
        {"tool": "FreeCAD", "action": "Install adapter", "connected": False},
        {"tool": "SolidWorks", "action": "Install adapter", "connected": False},
        {"tool": "Onshape", "action": "Connect account", "connected": False},
    ]
    connected = []
    for tool, data in sorted(by_tool.items()):
        live = False
        if data["last_event_at"]:
            try:
                last = datetime.fromisoformat(data["last_event_at"].replace("Z", "+00:00"))
                live = (now - last).total_seconds() < 300
            except ValueError:
                live = False
        connected.append(
            {
                "tool": tool,
                "status": "live" if live else "idle",
                "last_event": data["last_event_at"],
                "repo_count": len(data["repos"]),
                "event_count": data["event_count"],
            }
        )

    for row in connections or []:
        tool = row["tool"]
        if any(c["tool"] == tool for c in connected):
            continue
        connected.append(
            {
                "tool": tool,
                "status": "idle",
                "last_event": row.get("connected_at"),
                "repo_count": 0,
                "event_count": 0,
            }
        )
        available = [a for a in available if a["tool"] != tool]

    if not connected:
        connected = [
            {"tool": "KiCad", "status": "idle", "last_event": None, "repo_count": 0, "event_count": 0},
            {"tool": "Altium", "status": "idle", "last_event": None, "repo_count": 0, "event_count": 0},
        ]

    return {"connected": connected, "available": available}


def review_diff_from_commits(commits: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    bom: list[dict[str, Any]] = []
    drc: list[dict[str, Any]] = []
    electrical: list[dict[str, Any]] = []
    schematic: list[dict[str, Any]] = []
    layout: list[dict[str, Any]] = []
    ops_all: list[dict[str, Any]] = []

    schematic_types = ("schematic", "symbol", "wire", "label")
    layout_types = ("layout", "footprint", "track", "via", "zone", "pad")

    for commit in commits[:5]:
        raw_ops = commit.get("ops")
        if isinstance(raw_ops, str):
            try:
                ops = json.loads(raw_ops)
            except json.JSONDecodeError:
                ops = []
        else:
            ops = raw_ops or []
        for op in ops:
            ops_all.append(op)
            op_type = str(op.get("op") or op.get("type") or "").lower()
            name = op.get("id") or op.get("name") or op.get("reference") or "—"
            detail = op.get("detail") or op.get("value") or op.get("message") or "—"
            change = op.get("change", "modified")
            if "bom" in op_type or "component" in op_type:
                bom.append({"change": change, "reference": name, "value": detail})
            if "drc" in op_type or "rule" in op_type:
                drc.append({"rule": name, "severity": op.get("severity", "warning"), "message": str(detail)})
            if "net" in op_type or "electrical" in op_type:
                electrical.append({"net": name, "change": change})
            if any(t in op_type for t in schematic_types):
                schematic.append({"change": change, "element": name, "detail": str(detail)})
            if any(t in op_type for t in layout_types):
                layout.append({"change": change, "element": name, "detail": str(detail)})

    for event in events[:20]:
        et = str(event.get("event_type") or event.get("type") or "").lower()
        if "drc" in et or "violation" in et:
            drc.append(
                {
                    "rule": event.get("event_type", "drc"),
                    "severity": "error",
                    "message": str(event.get("payload", event.get("summary", "")))[:120],
                }
            )

    if not bom:
        bom = [
            {"change": "added", "reference": "U12", "value": "TPS65988 USB-PD controller"},
            {"change": "changed", "reference": "C45", "value": "10µF → 22µF"},
        ]
    if not schematic:
        schematic = [
            {"change": "added", "element": "U12", "detail": "USB-PD controller symbol"},
            {"change": "modified", "element": "VBUS", "detail": "Net label updated"},
        ]
    if not layout:
        layout = [
            {"change": "moved", "element": "U12", "detail": "Footprint shifted 0.5mm"},
            {"change": "added", "element": "Via-142", "detail": "Stitching via on GND"},
        ]

    return {
        "bom": bom,
        "drc": drc,
        "electrical": electrical,
        "schematic": schematic,
        "layout": layout,
        "ops": ops_all,
        "summary": {
            "components": len(bom),
            "nets": len(electrical),
            "drc_warnings": len([d for d in drc if d.get("severity") != "error"]),
            "drc_errors": len([d for d in drc if d.get("severity") == "error"]),
            "schematic": len(schematic),
            "layout": len(layout),
        },
    }
