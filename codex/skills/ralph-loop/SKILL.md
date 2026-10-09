---
name: ralph-loop
description: Run an explicitly requested bounded improvement loop over local code, backtests or CI with a machine-checkable stop condition.
---

Agree on scope, a machine-decidable success check, maximum iterations and durable
checkpoint path before running. The loop cannot edit its success check. Use
native Codex goal capabilities only when available and explicitly requested;
otherwise run bounded iterations in-session. Claude ralph Stop-hook state is not used.

Each iteration changes one supported hypothesis, runs the check, records results.
Stop on success, max iterations, two checkpoints without progress, repeated
identical failure, or user cancellation. Report incomplete work honestly.
Never touch live trading, venue writes, credentials or production risk settings.
Do not create unbounded background Stop-hook loops.
