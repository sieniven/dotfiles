---
name: tigerstyle
description: TigerBeetle's TigerStyle coding discipline as an opt-in standard, language-agnostic with Rust specifics. Safety, then performance, then developer experience; assertions on arguments, results and invariants (two per function on average, paired, positive and negative space); a limit on everything; no allocation after initialisation on hot paths; 70-line functions and 100-column lines; explicit control flow with no recursion; every error handled; units-last naming; back-of-envelope sketches and batching. Covers setting a repo up under it (a rules block, a single scripts/check gate, a ratchet for existing violations, clippy, rustfmt and cargo-deny settings), reviewing a diff against it with P0 to P3 findings, and writing code under it, reconciled with the Rust and Python language rules. Use when the user says TigerStyle or tiger style, asks for a TigerStyle review or setup, or works in a repo whose AGENTS.md or CLAUDE.md adopts TigerStyle.
---

# TigerStyle

Adapted from [fotoetienne/agent-essentials](https://github.com/fotoetienne/agent-essentials/tree/615a07f5145df00acea8da5cc0951e11462cf308/plugins/tiger-style) (MIT).

TigerBeetle's coding style, ported for this setup. Design goals in priority
order: **safety, then performance, then developer experience**. Style here is
design: a rule earns its place by making the code safer, faster or easier to
get right, in that order. It is opt-in: apply it where the user asks for it or
where the repo's AGENTS.md or CLAUDE.md adopts it, never as a default.

## Three uses, three references

Read the reference for the job before acting; the core rules below are a
shortlist, not the standard.

- **Set a repo up under TigerStyle**: read
  [references/setup.md](references/setup.md). It produces the rules block for
  the repo's AGENTS.md or CLAUDE.md, the `scripts/check` gate, the ratchet for
  violations that already exist, and where limit values come from. For a Rust
  repo also read the "Enforce it" section of
  [references/rust.md](references/rust.md).
- **Review a diff against it**: walk
  [references/review-checklist.md](references/review-checklist.md) over the
  diff, plus [references/rust.md](references/rust.md) for Rust.
- **Write code under it**: apply
  [references/principles.md](references/principles.md), plus
  [references/rust.md](references/rust.md) for Rust.

A narrow question the core rules answer ("what is the function limit?") needs
no reference.

## Precedence

1. The repo's own rules (its AGENTS.md, CLAUDE.md, lint config).
2. The language rules, `~/.codex/rules/<lang>.md`.
3. TigerStyle.

In a fork (reth, op-reth) the upstream project's conventions win over all
three. Where TigerStyle and a higher rule differ, follow the higher rule and
say so in one clause; do not argue the rule in review.

## Reconciliations

These are decided; apply them in every use.

- **Three kinds of failure, never mixed.** A broken invariant of our own
  panics (an assertion). Wrong external input (a venue, a peer, a file,
  config, a user) is a typed error naming what was wrong. Local exhaustion (a
  full queue, a reached cap) is a typed error or backpressure the caller sees.
  Never assert on external input, and never hide any of the three behind a
  default, a clamp or a silent drop.
- **Naming.** No abbreviations, units and qualifiers last
  (`latency_ms_max`), except the established trading vocabulary
  `rules/rust.md` allows (`px`, `qty`, `ts`).
- **Allocation.** "None after initialisation" binds hot paths and a
  deterministic simulated core. Cold paths follow `rules/rust.md`: off the hot
  path, don't pre-optimise.
- **Dependencies are not zero.** Each one is justified with its cost (what it
  pulls in, build time, binary share) and why std or an existing dependency
  will not do.
- **Comments and docs stay.** "Always say why" is TigerStyle's own rule, and
  the language rules require docs on public library items.
- **Unit tests stay**, and cover invalid data as well as valid, and the
  moment valid data becomes invalid.
- **Python:** `assert` is stripped under `-O`, so an invariant the code relies
  on is an explicit `raise` (`rules/python.md`).
- **Determinism** (clock, randomness, I/O, iteration order) and the lints that
  enforce it belong to the `deterministic-simulation-testing` skill.

## Core rules

1. **Assert what the code relies on**: arguments, results, pre- and
   postconditions, invariants; at least two assertions per function on
   average. Pair them across a boundary (checked where written and where read
   back), assert the negative space as well as the positive, split compound
   assertions, assert compile-time constant relationships.
2. **Put a limit on everything**: every loop, queue, buffer, batch, retry and
   depth has a named bound. Reaching it is an error or backpressure, never a
   silent drop. A loop that must not end (an event loop) asserts that.
3. **No recursion.** Walk input-shaped data iteratively, or with an explicit
   depth bound that returns an error.
4. **Functions of at most 70 lines**: push `if`s up and `for`s down; the
   parent owns control flow and state, leaves are pure.
5. **Lines of at most 100 columns**, the formatter always run, every compiler
   warning on at its strictest from day one.
6. **Handle every error**; a dropped one is a decision with a stated reason.
7. **Simple, explicit control flow**: split compound conditions into nested
   `if`/`else`, state invariants positively, pass library options explicitly.
8. **Smallest scope**: declare late, check close to use, no aliases or
   duplicated state.
9. **Name things well** (see Reconciliations) and say why in comments and
   commit messages.
10. **Back-of-envelope first**: network, disk, memory, CPU by bandwidth and
    latency, slowest first weighted by frequency; batch, and run at your own
    pace rather than reacting to each external event.

## Review output

```
## TigerStyle review: <target>

### P0: safety
- path/file.rs:42: `while let Some(m) = rx.recv()` drains an unbounded
  channel. Rule: put a limit on everything. Fix: bounded channel of
  ORDERS_IN_FLIGHT_MAX, reject with `QueueFull` when full.
### P1: assertions and function shape
### P2: naming, scope, comments
### P3: formatting and mechanics

### Already compliant
- <what the diff already does well>
```

Each finding carries `file:line`, the rule and a specific fix. Omit a level
with no findings; do not pad. Say what was already compliant. Note any rule
skipped because a higher rule or the language overrides it.

## When not to use it

- The repo has not opted in and the user did not ask: review against the
  repo's rules and the language rules instead.
- Framework-heavy code (a web framework, an ORM, a UI) whose idioms require
  allocation, deep abstraction or callbacks: flag the conflict and the
  trade-off, do not demand a rewrite.
- Test names and generated code are not held to the line and function
  limits.

## Sources

- Canonical, the tie-breaker:
  [TigerBeetle TIGER_STYLE.md](https://github.com/tigerbeetle/tigerbeetle/blob/0aeb306561365e21b97775c729bfc439f6c16d72/docs/TIGER_STYLE.md).
- Ported skill (MIT):
  [fotoetienne/agent-essentials tiger-style](https://github.com/fotoetienne/agent-essentials/tree/615a07f5145df00acea8da5cc0951e11462cf308/plugins/tiger-style).
- Rust application (MIT or Apache-2.0):
  [nanocode TIGER_STYLE.md](https://github.com/nanocodexyz/nanocode/blob/73d066e6fb3d503e4f1c54c6813cce34615c4c6a/TIGER_STYLE.md).
