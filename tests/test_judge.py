"""
judge-mcp tests — hermetic (LLM calls mocked) so they run anywhere
deterministically. Cover the wrapper contract: list/get rubric, judge with
both happy + edge cases, iterate loop logic, runtime rubric registration.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from judge_mcp import iterate as iterate_mod  # noqa: E402
from judge_mcp import rubrics as rubrics_mod  # noqa: E402
from judge_mcp.judge import judge_artifact  # noqa: E402
from judge_mcp.server import (  # noqa: E402
    get_rubric,
    iterate_until_threshold,
    judge_artifact as judge_tool,
    list_rubrics,
    register_rubric,
)


# ── Rubric loading ───────────────────────────────────────────────────


def test_builtin_rubrics_loaded():
    result = list_rubrics()
    ids = {r["id"] for r in result["rubrics"]}
    # The 8 ported rubrics must all be present.
    assert "sneaker-design" in ids
    assert "watch-design" in ids
    assert "writing-clarity" in ids
    assert "code-review" in ids
    assert "legal-clause" in ids
    assert "cold-email" in ids
    assert "resume-bullet" in ids
    assert "trikot-design" in ids


def test_get_rubric_returns_full_definition():
    r = get_rubric("code-review")
    assert "error" not in r
    assert r["name"] == "Code review (a function/diff)"
    assert len(r["criteria"]) == 4
    assert any(c["id"] == "correctness" and c["weight"] == 3 for c in r["criteria"])


def test_get_rubric_unknown_returns_clean_error():
    r = get_rubric("not-a-real-rubric")
    assert r.get("error") == "not_found"


# ── judge_artifact — happy path with mocked LLM ──────────────────────


def _mock_judge_response(criteria_scores: dict[str, int], summary: str = "ok"):
    """Build a fake LLM response in the JSON shape the judge expects."""
    return json.dumps(
        {
            "criteria": [
                {
                    "id": cid,
                    "score": score,
                    "evidence": "mocked evidence",
                    "fix": "mocked fix",
                }
                for cid, score in criteria_scores.items()
            ],
            "summary": summary,
        }
    )


def test_judge_artifact_computes_weighted_overall():
    """Weighted-mean math: criterion weight 3 counts 3x as much as weight 1."""
    fake = _mock_judge_response(
        {
            "correctness": 10,
            "robustness": 10,
            "security": 10,
            "clarity": 2,
        }
    )
    with patch("judge_mcp.judge.chat", return_value=fake):
        result = judge_tool("def add(a,b): return a+b", "code-review")

    # weights: correctness 3, robustness 2, security 2, clarity 1 → total 8
    # sum: 10*3 + 10*2 + 10*2 + 2*1 = 30+20+20+2 = 72; 72/8 = 9.0
    assert result["overall"] == 9.0
    assert result["rubric"] == "Code review (a function/diff)"
    assert len(result["criteria"]) == 4


def test_judge_artifact_unknown_rubric_returns_error():
    result = judge_tool("anything", "no-such-rubric")
    assert result.get("error") == "not_found"


def test_judge_artifact_handles_malformed_llm_json():
    """Bad LLM output → no crash, overall=0, criteria all score 0."""
    with patch("judge_mcp.judge.chat", return_value="not valid json at all"):
        result = judge_tool("artifact", "writing-clarity")
    assert result["overall"] == 0.0
    for c in result["criteria"]:
        assert c["score"] == 0.0


def test_judge_artifact_runs_regex_checks_alongside_llm():
    fake = _mock_judge_response(
        {"correctness": 8, "robustness": 6, "security": 7, "clarity": 5}
    )
    with patch("judge_mcp.judge.chat", return_value=fake):
        result = judge_tool(
            "def add(a,b): return a+b",
            "code-review",
            checks=[
                {"name": "has_return", "pattern": "return", "flags": "i"},
                {"name": "has_typehints", "pattern": ":\\s*int", "flags": "i"},
            ],
        )
    names = {c["name"]: c["pass"] for c in result["checks"]}
    assert names["has_return"] is True
    assert names["has_typehints"] is False


def test_judge_artifact_low_scores_produce_low_overall():
    fake = _mock_judge_response(
        {"clarity": 2, "concreteness": 3, "structure": 1, "no_fluff": 2}
    )
    with patch("judge_mcp.judge.chat", return_value=fake):
        result = judge_tool("vague stuff", "writing-clarity")
    assert result["overall"] < 4.0
    assert all(c["score"] <= 3 for c in result["criteria"])


# ── register_rubric ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_runtime_rubrics():
    """Each test starts with a clean runtime-rubric slate."""
    rubrics_mod._runtime_rubrics.clear()
    yield
    rubrics_mod._runtime_rubrics.clear()


def test_register_rubric_valid_spec():
    result = register_rubric(
        "my-custom",
        {
            "name": "Custom test rubric",
            "criteria": [
                {"id": "a", "name": "A", "weight": 1, "guide": "Does A."},
                {"id": "b", "name": "B", "weight": 2, "guide": "Does B."},
            ],
        },
    )
    assert result.get("registered") is True
    # Now retrievable via get_rubric
    full = get_rubric("my-custom")
    assert full["name"] == "Custom test rubric"
    # Listed with source=runtime
    listed = list_rubrics()["rubrics"]
    assert any(r["id"] == "my-custom" and r["source"] == "runtime" for r in listed)


def test_register_rubric_missing_name_rejected():
    result = register_rubric(
        "bad", {"criteria": [{"id": "x", "name": "x", "guide": "x"}]}
    )
    assert result.get("error") == "missing_fields"


def test_register_rubric_empty_criteria_rejected():
    result = register_rubric("bad", {"name": "x", "criteria": []})
    assert result.get("error") == "invalid_criteria"


def test_register_rubric_criterion_missing_guide_rejected():
    result = register_rubric(
        "bad",
        {
            "name": "x",
            "criteria": [{"id": "a", "name": "A"}],
        },
    )
    assert result.get("error") == "criterion_missing_field"


def test_register_rubric_weight_defaults_to_1():
    register_rubric(
        "weights-default",
        {
            "name": "X",
            "criteria": [{"id": "a", "name": "A", "guide": "g"}],
        },
    )
    full = get_rubric("weights-default")
    assert full["criteria"][0]["weight"] == 1


# ── iterate_until_threshold — loop logic ─────────────────────────────


def test_iterate_stops_when_threshold_reached_in_round_one():
    """First-round score >= threshold should exit immediately."""

    def _fake_generate(brief, *, prior, fixes, rubric, model=None):
        return "draft artifact"

    fake_judge = _mock_judge_response(
        {
            "clarity": 9,
            "concreteness": 9,
            "structure": 9,
            "no_fluff": 9,
        },
        summary="great first try",
    )

    with patch("judge_mcp.judge.chat", return_value=fake_judge):
        result = iterate_mod.iterate(
            brief="write a sentence",
            rubric=rubrics_mod.get_rubric("writing-clarity"),
            threshold=8.0,
            max_rounds=3,
            generate=_fake_generate,
        )

    assert len(result["rounds"]) == 1
    assert result["reached_bar"] is True
    assert result["best"]["overall"] == 9.0


def test_iterate_stops_on_plateau_to_save_cost():
    """Two consecutive non-improving rounds → stop early."""
    call_count = {"n": 0}

    def _fake_generate(brief, *, prior, fixes, rubric, model=None):
        call_count["n"] += 1
        return f"artifact v{call_count['n']}"

    # Same low score every round.
    fake_judge = _mock_judge_response(
        {
            "clarity": 4,
            "concreteness": 4,
            "structure": 4,
            "no_fluff": 4,
        }
    )

    with patch("judge_mcp.judge.chat", return_value=fake_judge):
        result = iterate_mod.iterate(
            brief="write something",
            rubric=rubrics_mod.get_rubric("writing-clarity"),
            threshold=8.0,
            max_rounds=5,
            generate=_fake_generate,
        )

    # Should stop at round 2 (plateau detection: round 2 score <= round 1).
    assert len(result["rounds"]) == 2
    assert result["reached_bar"] is False


def test_iterate_runs_full_budget_when_improving_but_below_threshold():
    """Improving each round but never reaches threshold → runs max_rounds."""
    scores = iter([5, 6, 7])

    def _fake_judge(*_args, **_kwargs):
        score = next(scores)
        return _mock_judge_response(
            {
                "clarity": score,
                "concreteness": score,
                "structure": score,
                "no_fluff": score,
            }
        )

    with patch("judge_mcp.judge.chat", side_effect=lambda *a, **k: _fake_judge()):
        result = iterate_mod.iterate(
            brief="write a sentence",
            rubric=rubrics_mod.get_rubric("writing-clarity"),
            threshold=9.0,
            max_rounds=3,
            generate=lambda *a, **k: "artifact",
        )

    assert len(result["rounds"]) == 3
    assert result["reached_bar"] is False
    assert result["best"]["overall"] == 7.0
