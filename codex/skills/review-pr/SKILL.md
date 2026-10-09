---
name: review-pr
description: Review a pull request across selected code, tests, comments, errors and type-design lenses when explicitly asked for a comprehensive review.
---

Establish the PR/head/base and read the actual diff plus repository guidance.
Choose relevant lenses: code-reviewer for bugs and conventions; pr-test-analyzer
for behavioral coverage; comment-analyzer for comment accuracy;
silent-failure-hunter for errors; type-design-analyzer for new invariants.
For trading execution paths add quant-trading-code-reviewer.

Propose scope, reviewer count and verification threshold before spending on a
multi-agent run; wait for per-run approval. Use native configured Codex roles,
collect every final report and consolidate findings with exact locations and
concrete failure scenarios. If delegation is unavailable, apply the lenses inline
and state that no independent reviewers ran.

Review is read-only. A simplification is a separate proposed change using
code-simplifier or code-simplifier-focused; do not silently apply it. Return
findings and recommended next steps in chat. No external comments, commits,
pushes or merges without the user's explicit instruction for that action.
