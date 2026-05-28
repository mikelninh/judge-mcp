"""
judge-mcp — domain-agnostic artifact judging + create-verify iteration as MCP.

This is the "MCP for MCPs" pattern: any other MCP server (gitlaw-mcp,
safevoice-mcp, grailsense, your custom thing) can call judge-mcp to score
its own outputs against a rubric, then loop until quality clears a bar.

The engine is pure — rubrics are data. To add a new domain, write a JSON
rubric and PR it into data/rubrics.json (or register at runtime via the
register_rubric tool).
"""

from __future__ import annotations

import json as _json
import logging
import os
import sys
import time
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from judge_mcp import iterate as _iterate_mod
from judge_mcp import rubrics as _rubrics_mod
from judge_mcp.judge import judge_artifact as _judge_artifact


log = logging.getLogger("judge_mcp")


def _log_json(level: int, **fields: Any) -> None:
    fields.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    log.log(level, _json.dumps(fields, ensure_ascii=False))


def _traced(tool_name: str):
    """Wrap a tool with request-id + latency logging + clean error envelopes."""

    def decorator(fn):
        def wrapper(*args, **kwargs):
            request_id = uuid.uuid4().hex[:12]
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                _log_json(
                    logging.INFO,
                    msg=f"tool.{tool_name}",
                    request_id=request_id,
                    tool=tool_name,
                    latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                    status="ok",
                )
                return result
            except Exception as e:  # pragma: no cover — defensive
                _log_json(
                    logging.ERROR,
                    msg=f"tool.{tool_name}",
                    request_id=request_id,
                    tool=tool_name,
                    latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                    status="error",
                    error=f"{type(e).__name__}: {e}",
                )
                return {"error": "internal_error", "message": str(e)}

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return decorator


mcp = FastMCP(
    "judge",
    host=os.getenv("FASTMCP_HOST", "0.0.0.0"),
    port=int(os.getenv("FASTMCP_PORT", os.getenv("PORT", "8003"))),
)


try:
    from starlette.responses import JSONResponse

    @mcp.custom_route("/health", methods=["GET"])
    async def _health(_request):  # noqa: ANN001
        return JSONResponse({"status": "ok", "service": "judge-mcp"})
except Exception:  # pragma: no cover
    pass


# ── Tool 1: list_rubrics ─────────────────────────────────────────────


@mcp.tool()
@_traced("list_rubrics")
def list_rubrics() -> dict[str, Any]:
    """
    Discover available rubrics — built-in (from data/rubrics.json) plus any
    runtime-registered ones from this server instance.

    Returns:
      {
        "rubrics": [
          {"id", "name", "source": "builtin"|"runtime",
           "criteria_count", "has_anchors", "has_examples"}
          ...
        ]
      }

    Use list_rubrics() first when you don't know what's available, then
    get_rubric(id) for the full definition before judging.
    """
    return {"rubrics": _rubrics_mod.list_rubrics()}


# ── Tool 2: get_rubric ───────────────────────────────────────────────


@mcp.tool()
@_traced("get_rubric")
def get_rubric(rubric_id: str) -> dict[str, Any]:
    """
    Full rubric definition: name, criteria (id, name, weight, guide), optional
    anchors (calibration: what a high vs low score looks like) and examples
    (calibration: artifacts with known scores).

    Returns the rubric dict, or {"error": "not_found", "rubric_id": <id>} when
    the id is unknown.
    """
    spec = _rubrics_mod.get_rubric(rubric_id)
    if spec is None:
        return {"error": "not_found", "rubric_id": rubric_id}
    return {"rubric_id": rubric_id, **spec}


# ── Tool 3: judge_artifact ───────────────────────────────────────────


@mcp.tool()
@_traced("judge_artifact")
def judge_artifact(
    artifact: str,
    rubric_id: str,
    checks: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Score an artifact against a rubric. The anti-vague-feedback tool.

    Args:
      artifact:  the text being scored (a code snippet, an email, a clause, a
                 design spec — anything domain-relevant for the rubric).
      rubric_id: a key from list_rubrics(). E.g. "code-review", "legal-clause",
                 "cold-email", "writing-clarity", "resume-bullet".
      checks:    optional list of {"name": str, "pattern": str, "flags": "i"}
                 regex checks that run alongside the LLM judge. Useful for
                 deterministic guarantees ("does it mention DSGVO?").
      model:     override the default LLM model (gpt-4o-mini). Set via env var
                 JUDGE_MCP_MODEL for the server default.

    Returns:
      {
        "rubric":   "<rubric.name>",
        "overall":  <0.0-10.0, weighted mean of criterion scores>,
        "criteria": [
          {"id", "name", "weight", "score" (1-10), "evidence" (≤22 words), "fix" (≤14 words)}
          ...
        ],
        "checks":  [{"name", "pass": bool} ...],
        "summary": "<≤18-word verdict>"
      }

    Or {"error": "not_found", "rubric_id": <id>} when the rubric_id is unknown.
    """
    spec = _rubrics_mod.get_rubric(rubric_id)
    if spec is None:
        return {"error": "not_found", "rubric_id": rubric_id}
    return _judge_artifact(artifact, spec, checks=checks, model=model)


# ── Tool 4: iterate_until_threshold ──────────────────────────────────


@mcp.tool()
@_traced("iterate_until_threshold")
def iterate_until_threshold(
    brief: str,
    rubric_id: str,
    threshold: float = 8.0,
    max_rounds: int = 3,
    checks: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Create-verify loop: generate an artifact for the brief, judge it, feed
    fixes back, regenerate, repeat until the score clears `threshold`,
    `max_rounds` is hit, or the loop plateaus (to save cost).

    This is the agentic quality-control primitive. Composes with any other
    MCP that can call MCPs: gitlaw-mcp answers a question, iterate scores
    the answer, loops until it's good.

    Args:
      brief:       what the artifact should accomplish ("Write a 3-line
                   cold email pitching X to Y mentioning Z…").
      rubric_id:   the rubric to score against (use list_rubrics() to find).
      threshold:   target overall score 0-10 (default 8). Stops as soon as reached.
      max_rounds:  budget cap on iterations (default 3).
      checks:      optional regex deterministic checks (see judge_artifact).
      model:       override the LLM model (default gpt-4o-mini).

    Returns:
      {
        "brief":       <input brief>,
        "threshold":   <float>,
        "rounds":      [{"round","artifact","overall","summary","criteria":[...]}, ...],
        "best":        {"round","artifact","overall","summary"},   ← what you ship
        "reached_bar": <bool — true if best.overall >= threshold>
      }

    Note: this tool spends LLM tokens — 1 generate + 1 judge per round, up to
    max_rounds. For a 3-round run on gpt-4o-mini, ~$0.005 typically.
    """
    spec = _rubrics_mod.get_rubric(rubric_id)
    if spec is None:
        return {"error": "not_found", "rubric_id": rubric_id}
    return _iterate_mod.iterate(
        brief,
        spec,
        checks=checks,
        threshold=threshold,
        max_rounds=max_rounds,
        model=model,
    )


# ── Tool 5: register_rubric ──────────────────────────────────────────


@mcp.tool()
@_traced("register_rubric")
def register_rubric(rubric_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """
    Add a rubric at runtime for this server instance. Survives only until
    the process restarts — for permanent rubrics, PR against data/rubrics.json
    instead.

    Spec shape:
      {
        "name": str,
        "criteria": [
          {"id": str, "name": str, "weight": int, "guide": str},
          ...
        ],
        "anchors": {"high": str, "low": str}   // optional
        "examples": [{"score": int, "artifact": str, "note": str}, ...]  // optional
      }

    Returns:
      {"registered": True, "rubric_id": <id>, "source": "runtime"}
      or {"error": ..., "message": ...}
    """
    return _rubrics_mod.register_rubric(rubric_id, spec)


# ── Entry point ──────────────────────────────────────────────────────


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(message)s",
        stream=sys.stderr,
    )
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if transport in ("sse", "streamable-http"):
        mcp.run(transport=transport)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
