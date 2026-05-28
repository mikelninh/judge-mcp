"""
Domain-agnostic judge — port of atelier-engine/lib/judge.js.

Takes an artifact (any string), a rubric (criteria + weights + optional
anchors/examples), and optional deterministic regex checks. Returns a
weighted verdict with per-criterion scores, evidence, and concrete fixes.

The engine NEVER changes per domain. To support a new domain you write a
rubric — see rubrics.py / data/rubrics.json.
"""

from __future__ import annotations

import re
from typing import Any

from judge_mcp.llm import chat, parse_json_lenient


def _build_system_prompt(rubric: dict[str, Any]) -> str:
    """Construct the system prompt the judge sends to the LLM."""
    if rubric.get("examples"):
        calib = (
            "Calibration examples — score the artifact RELATIVE to these reference points:\n"
            + "\n".join(
                f"  [{e['score']}/10] {e['artifact']}"
                + (f"  ({e['note']})" if e.get("note") else "")
                for e in rubric["examples"]
            )
        )
    elif rubric.get("anchors"):
        a = rubric["anchors"]
        calib = f'Calibration — high: "{a.get("high", "")}"; low: "{a.get("low", "")}".'
    else:
        calib = ""

    criteria_summary = " | ".join(
        f"{c['id']} ({c['name']}: {c['guide']})" for c in rubric["criteria"]
    )

    return (
        "You are an impartial, calibrated evaluator. Judge the ARTIFACT strictly against the RUBRIC.\n"
        "For each criterion: a score 1-10, the specific EVIDENCE from the artifact (or note its absence), "
        "and one concrete FIX.\n"
        "Be critical and calibrated — reserve 9-10 for genuinely excellent work; most drafts are 4-7. "
        "Do not reward vagueness.\n"
        f"{calib}\n"
        "Return ONLY valid JSON:\n"
        '{"criteria":[{"id":"...","score":1-10,"evidence":"under 22 words",'
        '"fix":"under 14 words"}],"summary":"under 18 words"}\n'
        f"Criteria (use these exact ids): {criteria_summary}"
    )


def _run_checks(
    artifact: str, checks: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Optional regex-based deterministic checks — runs alongside the LLM judge."""
    if not checks:
        return []
    out: list[dict[str, Any]] = []
    for c in checks:
        try:
            pattern = re.compile(
                c["pattern"], re.IGNORECASE if "i" in (c.get("flags") or "") else 0
            )
            out.append(
                {
                    "name": c.get("name", c["pattern"]),
                    "pass": bool(pattern.search(artifact)),
                }
            )
        except re.error as e:
            out.append(
                {"name": c.get("name", "<bad_pattern>"), "pass": False, "error": str(e)}
            )
    return out


def judge_artifact(
    artifact: str,
    rubric: dict[str, Any],
    *,
    checks: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Score an artifact against a rubric.

    Returns:
      {
        "rubric": "<rubric.name>",
        "overall": <float 0-10, weighted average of criterion scores>,
        "criteria": [
          {"id", "name", "weight", "score" (1-10), "evidence" (≤22 words), "fix" (≤14 words)}
          ...
        ],
        "checks": [{"name", "pass": bool} ...],  // empty if no checks were passed in
        "summary": "<≤18-word verdict>"
      }
    """
    check_results = _run_checks(artifact, checks)
    system = _build_system_prompt(rubric)

    raw = chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"ARTIFACT:\n\n{artifact}"},
        ],
        max_tokens=700,
        temperature=0.3,
        json_mode=True,
        model=model,
    )
    parsed = parse_json_lenient(raw, default={"criteria": []})

    by_id = {c.get("id"): c for c in (parsed.get("criteria") or []) if c.get("id")}

    weighted_sum = 0.0
    total_weight = 0.0
    criteria_out: list[dict[str, Any]] = []

    for c in rubric["criteria"]:
        rec = by_id.get(c["id"], {})
        try:
            score = float(rec.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        weight = c.get("weight", 1)
        weighted_sum += score * weight
        total_weight += weight
        criteria_out.append(
            {
                "id": c["id"],
                "name": c["name"],
                "weight": weight,
                "score": score,
                "evidence": rec.get("evidence", ""),
                "fix": rec.get("fix", ""),
            }
        )

    overall = round(weighted_sum / total_weight, 1) if total_weight else 0.0

    return {
        "rubric": rubric.get("name", "unnamed"),
        "overall": overall,
        "criteria": criteria_out,
        "checks": check_results,
        "summary": (parsed.get("summary") or "").strip(),
    }
