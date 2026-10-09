---
name: code-review
description: Review a GitHub PR or local diff for concrete bugs and applicable repository rules when asked for code review.
---

Read the actual diff and relevant unchanged callers. Establish intended behavior,
applicable AGENTS.md and language rules. For trading execution paths, read the
domain and venue skills and use the quant-trading review criteria.

Each finding needs an exact location, a concrete failure and evidence that
surrounding guards do not prevent it. Discard speculative, pre-existing and
purely stylistic issues. Report by severity with file/line links; state limits
and tests not run. An approved independent workflow can use code-reviewer,
silent-failure-hunter, pr-test-analyzer, comment-analyzer or type-design-analyzer.
Do not silently spawn a panel; collect all reviewers before reporting.
Never merge, push or change code as part of read-only review. Post GitHub
comments only when explicitly asked; otherwise return the review in chat.
