# judge-mcp Gauntlet Optimizer

Optimize the **judge**, not the artifacts it scores.

1. Run `judge-gauntlet` on the frozen human-labelled calibration suite.
2. Record mean absolute error, within-one-point rate and all adversarial hard gates.
3. Inspect the largest systematic calibration error: verbosity bias, prompt-injection susceptibility, weak evidence binding, score compression/inflation, or rubric interpretation.
4. State one falsifiable hypothesis.
5. Change one coherent surface only: judge system prompt, evidence extraction, calibration anchors, scoring procedure or deterministic pre-check.
6. Rerun the complete suite with the same model and settings.
7. Never change human scores or benchmark artifacts because the candidate disagrees with them.
8. Any prompt-injection hard-gate failure => `REVERT`.
9. Otherwise `KEEP` only if held-out human agreement improves without a new systematic bias.
10. Record the experiment in Git.

The judge must never be its own sole fitness function. Human-labelled and deterministic cases are the external reference.
