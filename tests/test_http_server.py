from __future__ import annotations

from judge_mcp import http_server


def test_http_judge_rejects_missing_artifact():
    status, body = http_server.judge_http_payload({"rubric_id": "code-review"})
    assert status == 400
    assert body["error"] == "artifact_required"


def test_http_judge_rejects_unknown_rubric():
    status, body = http_server.judge_http_payload(
        {"artifact": "hello", "rubric_id": "does-not-exist"}
    )
    assert status == 404
    assert body["error"] == "rubric_not_found"


def test_http_judge_bounds_artifact_size():
    status, body = http_server.judge_http_payload(
        {"artifact": "x" * 50_001, "rubric_id": "code-review"}
    )
    assert status == 413
    assert body["error"] == "artifact_too_large"


def test_http_judge_rejects_unbounded_checks():
    status, body = http_server.judge_http_payload(
        {
            "artifact": "hello",
            "rubric_id": "code-review",
            "checks": [{"name": f"c-{i}", "pattern": "x"} for i in range(21)],
        }
    )
    assert status == 400
    assert body["error"] == "checks_invalid"


def test_http_judge_delegates_to_existing_engine(monkeypatch):
    captured = {}

    def fake_judge(artifact, spec, checks=None, model=None):
        captured.update(
            artifact=artifact,
            rubric_name=spec["name"],
            checks=checks,
            model=model,
        )
        return {
            "rubric": spec["name"],
            "overall": 9.1,
            "criteria": [],
            "checks": [{"name": "mentions evidence", "pass": True}],
            "summary": "Strong and reviewable.",
        }

    monkeypatch.setattr(http_server, "_judge_artifact", fake_judge)
    status, body = http_server.judge_http_payload(
        {
            "artifact": "Evidence-backed answer.",
            "rubric_id": "writing-clarity",
            "checks": [{"name": "mentions evidence", "pattern": "evidence", "flags": "i"}],
            "model": "caller-controlled-model-must-be-ignored",
        }
    )

    assert status == 200
    assert body["schema"] == "open-capabilities.provider/1"
    assert body["capabilityId"] == "agent.output.judge.v1"
    assert body["result"]["overall"] == 9.1
    assert body["authority"]["consequentialActionExecuted"] is False
    assert captured["model"] is None
    assert captured["checks"][0]["name"] == "mentions evidence"
