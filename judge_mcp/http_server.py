"""HTTP interoperability facade for judge-mcp.

Keeps the native MCP server intact while exposing one bounded REST endpoint
that OpenCapabilities-compatible gateways can call.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

from starlette.responses import JSONResponse

from judge_mcp import rubrics as _rubrics_mod
from judge_mcp.judge import judge_artifact as _judge_artifact
from judge_mcp.server import mcp

CAPABILITY_ID = "agent.output.judge.v1"
_SCHEMA = "open-capabilities.provider/1"
_RUBRIC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
_MAX_ARTIFACT_CHARS = 50_000
_MAX_CHECKS = 20
_MAX_PATTERN_CHARS = 1_000


def _validate_checks(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > _MAX_CHECKS:
        raise ValueError("checks_invalid")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("checks_invalid")
        name = item.get("name")
        pattern = item.get("pattern")
        flags = item.get("flags")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("check_name_invalid")
        if not isinstance(pattern, str) or not pattern or len(pattern) > _MAX_PATTERN_CHARS:
            raise ValueError("check_pattern_invalid")
        if flags not in (None, "", "i"):
            raise ValueError("check_flags_invalid")
        result.append({"name": name.strip(), "pattern": pattern, **({"flags": flags} if flags else {})})
    return result


def judge_http_payload(payload: Any) -> tuple[int, dict[str, Any]]:
    """Validate a REST request and delegate to the existing judge engine."""
    if not isinstance(payload, dict):
        return 400, {"error": "body_must_be_object"}

    artifact = payload.get("artifact")
    rubric_id = payload.get("rubric_id")
    if not isinstance(artifact, str) or not artifact.strip():
        return 400, {"error": "artifact_required"}
    if len(artifact) > _MAX_ARTIFACT_CHARS:
        return 413, {"error": "artifact_too_large", "maxChars": _MAX_ARTIFACT_CHARS}
    if not isinstance(rubric_id, str) or not _RUBRIC_ID_RE.fullmatch(rubric_id):
        return 400, {"error": "rubric_id_invalid"}

    spec = _rubrics_mod.get_rubric(rubric_id)
    if spec is None:
        return 404, {"error": "rubric_not_found", "rubric_id": rubric_id}

    try:
        checks = _validate_checks(payload.get("checks"))
    except ValueError as exc:
        return 400, {"error": str(exc)}

    # External callers cannot choose the model. Operations controls the model
    # through JUDGE_MCP_MODEL, keeping cost and data-routing policy server-side.
    result = _judge_artifact(artifact, spec, checks=checks, model=None)
    if isinstance(result, dict) and result.get("error"):
        return 502, {"error": "judge_failed", "provider": result}

    return 200, {
        "schema": _SCHEMA,
        "capabilityId": CAPABILITY_ID,
        "result": result,
        "authority": {
            "consequentialActionExecuted": False,
            "humanApprovalRequired": False,
        },
    }


@mcp.custom_route("/v1/judge", methods=["POST"])
async def _judge_http(request):  # noqa: ANN001
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    status, body = judge_http_payload(payload)
    return JSONResponse(body, status_code=status)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(message)s",
        stream=sys.stderr,
    )
    # The interoperability server is HTTP-only by design. Native `judge-mcp`
    # continues to support stdio/SSE/streamable-http through server.py.
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
