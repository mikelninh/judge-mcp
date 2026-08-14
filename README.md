# judge-mcp ⚖️

**The MCP for MCPs: evaluate an artifact against a rubric, explain the score, and iterate until quality clears a threshold.**

[![Tests](https://img.shields.io/badge/tests-16%2F16-brightgreen?logo=pytest)](tests/) [![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

## The idea

```text
artifact + rubric
       ↓
structured evaluation
       ↓
criterion scores + evidence + fixes
       ↓
revision
       ↓
re-evaluate
       ↓
threshold reached or loop stops
```

Instead of giving every agent or MCP server its own ad-hoc evaluator, `judge-mcp` exposes evaluation as a composable tool.

## Core tools

| Tool | Purpose |
| --- | --- |
| `list_rubrics()` | discover available rubrics |
| `get_rubric()` | inspect criteria, weights and anchors |
| `judge_artifact()` | score an artifact and return evidence + fixes |
| `iterate_until_threshold()` | create → judge → revise until threshold or plateau |
| `register_rubric()` | add a runtime rubric without changing code |

## Example

```python
judge_artifact(
    artifact="def add(a, b): return a + b",
    rubric_id="code-review",
)
```

returns a structured result with:

- overall weighted score
- per-criterion scores
- evidence for each score
- concrete improvement suggestions

## Why it is useful

An agent can compose specialised tools rather than trusting one model call to do everything:

```text
GitLaw retrieves grounded legal sources
          ↓
agent prepares an artifact
          ↓
judge-mcp evaluates it against a rubric
          ↓
agent revises or escalates
```

The evaluator is a **quality-control primitive**, not a claim that an LLM score is objective truth.

## Built-in rubrics

Starter rubrics cover:

- code review
- writing clarity
- legal clauses
- cold email
- resume bullets
- product/design specifications

Rubrics are data rather than hard-coded domain logic, so new domains can be added without rewriting the evaluation engine.

## Tests

```text
16 passed
```

The suite covers rubric discovery, weighted scoring, malformed outputs, runtime rubric registration, threshold stopping and plateau detection. LLM calls are mocked so the tests are hermetic.

## Quickstart

```bash
git clone https://github.com/mikelninh/judge-mcp
cd judge-mcp
pip install -e .
```

Then connect the `judge-mcp` command from an MCP-compatible client.

## Honest limits

- LLM scoring is calibrated, not absolute.
- Rubric quality determines evaluation quality.
- Iterative judging consumes additional tokens.
- v0.1 uses one model provider path.
- Runtime-registered rubrics are currently ephemeral.

## Stack

**Python · MCP · structured outputs · rubric-based evaluation · deterministic checks · hermetic tests**

---

Built by [Michael Ninh](https://mikelninh.github.io/) in Berlin. · MIT
