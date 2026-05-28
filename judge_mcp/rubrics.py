"""
Rubrics — loaded from data/rubrics.json. Adding a domain is a JSON edit, not
a code change. That's deliberate: judges are tools, rubrics are policy.

Customers / contributors register their own rubrics via:
  - PR against this repo's rubrics.json (becomes built-in)
  - register_rubric() MCP tool at runtime (per-instance, ephemeral)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RUBRICS_FILE = Path(__file__).parent / "data" / "rubrics.json"

# Runtime-registered rubrics live in-memory only — call register_rubric()
# again after server restart. This keeps the on-disk JSON the public record.
_runtime_rubrics: dict[str, dict[str, Any]] = {}


def _builtin_rubrics() -> dict[str, dict[str, Any]]:
    return json.loads(RUBRICS_FILE.read_text(encoding="utf-8"))["rubrics"]


def list_rubrics() -> list[dict[str, Any]]:
    """All rubrics — built-in + runtime — with summary metadata only (not the full criteria)."""
    out: list[dict[str, Any]] = []
    for src, source in (("builtin", _builtin_rubrics()), ("runtime", _runtime_rubrics)):
        for rid, r in source.items():
            out.append(
                {
                    "id": rid,
                    "name": r["name"],
                    "source": src,
                    "criteria_count": len(r["criteria"]),
                    "has_anchors": "anchors" in r,
                    "has_examples": "examples" in r,
                }
            )
    return out


def get_rubric(rubric_id: str) -> dict[str, Any] | None:
    """Full rubric definition or None if not found."""
    return _runtime_rubrics.get(rubric_id) or _builtin_rubrics().get(rubric_id)


def register_rubric(rubric_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """
    Add a rubric at runtime. Validates the minimum shape (name + criteria with
    id/name/weight/guide). Stores in-memory only — survives until server restart.

    For permanent rubrics: PR against data/rubrics.json instead.
    """
    if not rubric_id or not isinstance(rubric_id, str):
        return {
            "error": "invalid_id",
            "message": "rubric_id must be a non-empty string",
        }
    if not isinstance(spec, dict):
        return {"error": "invalid_spec", "message": "spec must be a dict"}
    if "name" not in spec or "criteria" not in spec:
        return {
            "error": "missing_fields",
            "message": "spec needs at least 'name' and 'criteria'",
        }
    criteria = spec.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return {
            "error": "invalid_criteria",
            "message": "criteria must be a non-empty list",
        }
    for c in criteria:
        for field in ("id", "name", "guide"):
            if field not in c:
                return {
                    "error": "criterion_missing_field",
                    "message": f"each criterion needs '{field}'",
                    "criterion": c,
                }
        c.setdefault("weight", 1)

    _runtime_rubrics[rubric_id] = spec
    return {"registered": True, "rubric_id": rubric_id, "source": "runtime"}
