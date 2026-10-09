---
name: skill-comply
description: Measure whether a skill, rule or agent follows checkable obligations using approved isolated scenarios and independent grading.
---

Read the target and extract observable obligations with source quotes and checks.
Use supportive, neutral and competing tasks, or seeded fixtures under
fixtures/quant-trading-code-reviewer/. Do not edit expectations to make a run pass.
Report planned model-call cost; get approval for the spec and run plan before spending.

Agent targets use their configured Codex role in an isolated workspace. Skill/rule
targets may use codex exec --json if config loads the target and writes stay inside
the workspace; use --no-daemon when isolation from a desktop daemon matters.
Never run claude -p or write Claude state. Default one run per scenario; use three
before changing a definition based on measured compliance.

Collect result/trace, then give an independent grader the spec, scenario and raw
output without the intended conclusion. Score complied/violated/not-applicable
with evidence. Check ordering mechanically. Grade seeded cases against expected.yaml.
Read fixtures/README.md for the trading-review corpus.

Report per-obligation and per-scenario compliance, applicable denominator, limits
and concrete fixes: hook, earlier routing, rewording or deletion of uncheckable
prose. Structural validation is not behavioral compliance. Apply no fixes without
approval. Save results in an approved workspace or codex/local/evaluations/.
Never touch live trading or external write APIs.
