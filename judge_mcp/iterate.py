"""
Create-and-verify loop — port of atelier-engine/lib/iterate.js.

generate → judge → feed fixes back → repeat until the artifact clears
`threshold`, hits `max_rounds`, or stops improving (plateau, to save cost).

Domain-agnostic: the rubric decides "good". The generator is also pluggable —
default uses OpenAI but the MCP tool accepts a brief and runs the OpenAI
generator internally. Advanced callers (a meta-MCP, an agent) can call
judge_artifact() directly and supply their own generator.
"""

from __future__ import annotations

from typing import Any, Callable

from judge_mcp.judge import judge_artifact
from judge_mcp.llm import chat


def _default_generate(
    brief: str,
    *,
    prior: str | None,
    fixes: list[str] | None,
    rubric: dict[str, Any] | None,
    model: str | None = None,
) -> str:
    """Default OpenAI-backed generator. Rubric-aware — writes TOWARD the criteria."""
    criteria_block = ""
    if rubric and rubric.get("criteria"):
        criteria_block = (
            "\n\nThe artifact will be scored on these criteria — optimise for all of them:\n"
            + "\n".join(f"- {c['name']}: {c['guide']}" for c in rubric["criteria"])
        )

    system = (
        "You produce a single ARTIFACT for the BRIEF. Be specific and concrete; use real "
        "details from the brief; cut filler and buzzwords. If a PRIOR ARTIFACT and FIXES "
        "are given, revise to address EVERY fix while keeping what already works."
        f"{criteria_block}\n"
        "Output ONLY the artifact itself — no preamble, no commentary, no markdown fences."
    )

    if prior is not None and fixes:
        user = (
            f"BRIEF: {brief}\n\n"
            f"PRIOR ARTIFACT:\n{prior}\n\n"
            "FIXES TO ADDRESS:\n" + "\n".join(f"- {f}" for f in fixes)
        )
    else:
        user = f"BRIEF: {brief}"

    return chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=600,
        temperature=0.6,
        model=model,
    ).strip()


def iterate(
    brief: str,
    rubric: dict[str, Any],
    *,
    checks: list[dict[str, Any]] | None = None,
    threshold: float = 8.0,
    max_rounds: int = 3,
    generate: Callable[..., str] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Returns:
      {
        "brief": "<the brief>",
        "threshold": <float>,
        "rounds": [
          {"round", "artifact", "overall", "summary", "criteria": [...]}
        ],
        "best": {"round", "artifact", "overall", "summary"},
        "reached_bar": <bool>
      }
    """
    gen = generate or _default_generate

    rounds: list[dict[str, Any]] = []
    artifact = gen(brief, prior=None, fixes=None, rubric=rubric, model=model)
    best: dict[str, Any] | None = None

    for r in range(1, max_rounds + 1):
        verdict = judge_artifact(artifact, rubric, checks=checks, model=model)
        rounds.append(
            {
                "round": r,
                "artifact": artifact,
                "overall": verdict["overall"],
                "summary": verdict["summary"],
                "criteria": verdict["criteria"],
            }
        )
        if best is None or verdict["overall"] > best["overall"]:
            best = {
                "round": r,
                "artifact": artifact,
                "overall": verdict["overall"],
                "summary": verdict["summary"],
            }

        if verdict["overall"] >= threshold:
            break
        # Plateau / regression — stop spending tokens on a stuck loop.
        if r >= 2 and verdict["overall"] <= rounds[r - 2]["overall"]:
            break
        if r == max_rounds:
            break

        fixes = [
            c["fix"]
            for c in verdict["criteria"]
            if c["score"] < threshold and c.get("fix")
        ]
        artifact = gen(brief, prior=artifact, fixes=fixes, rubric=rubric, model=model)

    assert best is not None
    return {
        "brief": brief,
        "threshold": threshold,
        "rounds": rounds,
        "best": best,
        "reached_bar": best["overall"] >= threshold,
    }
