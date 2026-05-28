# judge-mcp

**Domain-agnostic artifact judging + create-verify iteration as MCP tools.**
The "MCP for MCPs" — score any artifact against any rubric, iterate until quality clears a bar.

[![Tests](https://img.shields.io/badge/tests-16%2F16-brightgreen?logo=pytest)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-server-blue)](https://modelcontextprotocol.io)

---

## What this is

A judge that doesn't care what it's judging. You feed it an **artifact** (any text)
plus a **rubric** (criteria with weights, plus optional anchors and calibration
examples) — it returns a weighted score 0-10, with per-criterion evidence and
concrete fixes.

```python
judge_artifact(
    artifact="def add(a,b): return a+b",
    rubric_id="code-review",
)
→ {
    "rubric": "Code review (a function/diff)",
    "overall": 5.5,
    "criteria": [
      {"id": "correctness", "score": 7, "evidence": "...", "fix": "validate inputs"},
      {"id": "robustness",  "score": 4, "evidence": "no type check", "fix": "..."},
      ...
    ],
    "summary": "Works for happy path, no input validation, no error handling."
  }
```

Pair it with `iterate_until_threshold(brief, rubric_id, threshold=8)` and you get
an automatic create→judge→fix→regenerate loop that stops when quality is reached
or the loop plateaus (to save tokens).

---

## Why this exists — the "MCP for MCPs" idea

Once you have a few MCP servers in the wild (e.g.
[gitlaw-mcp](https://github.com/mikelninh/gitlaw),
[safevoice-mcp](https://github.com/mikelninh/safevoice/tree/main/safevoice_mcp))
each one produces artifacts: a legal answer, a Strafanzeige draft, a generated
template. **Quality of those artifacts is the bottleneck for agentic
workflows.** Today every MCP either ships its own ad-hoc eval, or none at all.

`judge-mcp` is the missing piece: **one server, every other MCP can call it.**

- A `gitlaw-mcp` answer can be scored against the `legal-clause` rubric before
  the agent surfaces it to the user
- A `safevoice-mcp` draft can be iterated against a custom victim-protection
  rubric until it's court-ready
- Your own MCP can compose `iterate_until_threshold` to auto-improve outputs
  without writing the loop yourself

The rubrics are **data, not code** — adding a new domain is a JSON edit (PR
against `data/rubrics.json`), or a runtime registration via `register_rubric()`.

This is a deliberate inversion of the usual "evaluation framework" pattern.
Instead of bolting an evaluator onto a specific tool, the evaluator is a
network-callable primitive that any tool can compose with.

---

## Tools exposed

| Tool | What it does |
|---|---|
| `list_rubrics()` | Discover available rubrics — built-in (from `data/rubrics.json`) and runtime-registered |
| `get_rubric(rubric_id)` | Full rubric definition: criteria, weights, anchors, examples |
| `judge_artifact(artifact, rubric_id, checks?)` | Score an artifact. Returns overall + per-criterion scores + evidence + fixes |
| `iterate_until_threshold(brief, rubric_id, threshold, max_rounds)` | Create-verify loop: generate → judge → fix → regenerate until score ≥ threshold |
| `register_rubric(rubric_id, spec)` | Add a custom rubric at runtime (per-instance, ephemeral) |

## Built-in rubrics (the eight starter set)

| ID | Domain |
|---|---|
| `sneaker-design` | Sneaker product spec quality |
| `watch-design` | Watch product spec quality |
| `trikot-design` | Sports kit design quality |
| `writing-clarity` | Domain-agnostic prose |
| `code-review` | Function/diff review (correctness, robustness, security, clarity) |
| `legal-clause` | Contract clause quality (clarity, completeness, balance, enforceability) |
| `cold-email` | Cold outreach reply-worthiness |
| `resume-bullet` | CV bullet strength (impact, ownership, specificity, concision) |

More via PR. Or register your own at runtime.

---

## Quickstart — Claude Desktop in one minute

```bash
git clone https://github.com/mikelninh/judge-mcp
cd judge-mcp
pip install -e .
```

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "judge": {
      "command": "judge-mcp",
      "env": { "OPENAI_API_KEY": "sk-..." }
    }
  }
}
```

Restart Claude Desktop. Try:

> *"Score this Python function against the code-review rubric: `def add(a,b): return a+b`"*

For Cursor / Continue / any MCP client — same config schema.

---

## Composition pattern (the magic)

Once `judge-mcp` is wired in alongside other MCP servers, an agent can do this
in one conversation:

```
1. gitlaw-mcp.search_laws("Mieterhöhung Zustimmung")
   → returns § 558 BGB and adjacent paragraphs

2. <agent drafts a tenant response letter citing § 558 BGB>

3. judge-mcp.judge_artifact(draft_letter, rubric_id="legal-clause")
   → overall 6.5, fixes: "name the specific Kappungsgrenze",
                        "cite the exact Frist for response"

4. <agent revises the letter addressing the fixes>

5. judge-mcp.judge_artifact(revised_letter, rubric_id="legal-clause")
   → overall 8.2, ready to ship
```

No human in the loop. The agent uses one MCP for facts, another for quality
control. **That's MCP composition — and judge-mcp is what makes it work for any
artifact-producing server.**

For full automation, replace steps 2–5 with one `iterate_until_threshold` call.

---

## Test coverage

```
16 passed in ~1s
```

- 3 rubric-discovery tests (load all 8 built-ins, full definition, unknown handling)
- 5 `judge_artifact` tests (weighted-mean math, unknown rubric, malformed LLM
  output, regex checks alongside LLM, low-score path)
- 5 `register_rubric` tests (valid spec, missing fields, empty criteria,
  missing criterion field, weight defaults)
- 3 `iterate_until_threshold` tests (stops at threshold, plateau-stop saves
  tokens, runs full budget while improving)

All LLM calls are mocked — tests are hermetic and run in any CI without
secrets or network.

---

## Honest limits

- **Single LLM provider (OpenAI) in v0.1.** Anthropic + Gemini gateway on the
  roadmap, but the architecture is provider-agnostic — only `llm.py` would
  change.
- **No persistent state.** Runtime-registered rubrics live in memory only.
  Permanent rubrics → PR against `data/rubrics.json`.
- **The judge spends tokens.** Each `judge_artifact` call is one LLM
  completion; `iterate_until_threshold` is up to `max_rounds * 2` calls
  (generate + judge per round). Budget accordingly.
- **Scoring is calibrated, not absolute.** Two different LLMs scoring the
  same artifact against the same rubric will diverge by ~0.5-1.5 points.
  Use the same model across runs for consistency.
- **Rubrics are opinions encoded as data.** Disagree with one? Open a
  discussion or fork the rubric in your own registration.

---

## Part of an MCP-server portfolio

`judge-mcp` is the meta-tool in a small portfolio of public-good Model Context
Protocol servers:

- **[gitlaw-mcp](https://github.com/mikelninh/gitlaw)** — German federal law: search, citation verification, drift detection, trust statement
- **[safevoice-mcp](https://github.com/mikelninh/safevoice/tree/main/safevoice_mcp)** — Digital-harassment victim tooling: classify, applicable §, Strafantrag-Fristen, jurisdiction (DE/AT/CH/UK)
- **[grailsense](https://github.com/mikelninh/grailsense)** — NFT collector intelligence over Blockscout: archetype classification + shareable soul cards
- **[judge-mcp](https://github.com/mikelninh/judge-mcp)** ← you're here — domain-agnostic judge + iterate engine

Same architectural pattern across all four: thin MCP wrapper over a small,
testable core. Each one is a few hundred lines of Python, MIT-licensed,
designed to compose.

---

## Roadmap

- [ ] Anthropic + Gemini gateway via [Vercel AI Gateway](https://vercel.com/ai/ai-gateway)
- [ ] Self-judge: a `meta-judge` rubric that scores rubrics for quality
- [ ] Calibration learning: human-score overrides become anchors over time
- [ ] More built-in rubrics (currently 8; community PRs welcome)
- [ ] Hosted SSE deployment for non-local agents
- [ ] Cost tracking per call (surface token spend in tool output)

---

## Contributing

Adding a rubric:
1. Edit `judge_mcp/data/rubrics.json`
2. Open a PR

The schema is documented in the file itself + in `register_rubric` source.
Each criterion needs `id`, `name`, `guide`, optional `weight` (default 1).

---

## License

MIT.
