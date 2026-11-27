# TigerStyle review checklist

Adapted from [fotoetienne/agent-essentials](https://github.com/fotoetienne/agent-essentials/tree/615a07f5145df00acea8da5cc0951e11462cf308/plugins/tiger-style) (MIT).

Walk this list over the target: a diff, a PR, a file or a function. The rules
and their rationale are in [principles.md](principles.md); the precedence and
reconciliations in [../SKILL.md](../SKILL.md) decide any conflict.

## Process

1. Scope: `git diff main...HEAD`, a PR, or the named files.
2. Language: for Rust also read [rust.md](rust.md) and
   `~/.codex/rules/rust.md`; for Python, `~/.codex/rules/python.md`. Check
   the repo's own rules first: they win.
3. Run the gate if the repo has one (`scripts/check`, see
   [setup.md](setup.md)); a mechanical finding a check already reports needs
   no hand review, only the fix.
4. Walk the checklist; group findings P0 to P3.
5. Report in the format in [../SKILL.md](../SKILL.md): `file:line`, the rule,
   a specific fix. Say what is already compliant.

## P0: safety (fix before merge)

- [ ] **Unbounded loops, queues, buffers, retries, batches.** Every one has a
      named fixed bound; an event loop asserts that it does not end.
- [ ] **A reached bound that drops silently** instead of returning a typed
      error or applying backpressure.
- [ ] **Allocation on a hot path or in a deterministic core after
      initialisation**: growing collections per message, unbounded channels,
      per-event `format!` or `collect()`.
- [ ] **Unhandled errors**: a swallowed error, `let _ =` or `_ =` on a
      `Result`, a bare `except`, an error turned into a default, clamp or
      truncation on a value that matters.
- [ ] **Failure kinds mixed**: an assertion on external input (venue, peer,
      file, config, user), or a broken invariant returned as an ordinary error
      that flows on.
- [ ] **Recursion**, or input-shaped data walked without a depth bound.
- [ ] **Compound boolean conditions hiding unhandled cases.** Split into
      nested `if`/`else` and check every branch.
- [ ] **An `if` without an `else`** where the negative space matters.
- [ ] **Python invariants as `assert`**, which `-O` strips.

## P1: assertions

- [ ] **Arguments unchecked**: bounds, invariants the caller must uphold that
      the type does not already guarantee.
- [ ] **Results and postconditions unasserted**, especially at module
      boundaries.
- [ ] **Invariants unasserted**: loop invariants, state transitions, "sorted
      at this point".
- [ ] **Density under two per function**, averaged across the diff.
- [ ] **Unpaired assertions**: a property checked where written but not where
      read back.
- [ ] **Negative space unasserted**: only the happy path checked.
- [ ] **Compound assertions** (`assert(a && b)`): split them.
- [ ] **Library defaults relied on** where options should be explicit.

## P1: function shape

- [ ] **Functions over 70 lines.** Split: control flow in the parent, pure
      leaves.
- [ ] **Many parameters**, or same-typed parameters that can be swapped
      without a named options struct.
- [ ] **Branching leaves**: push the `if`s up.
- [ ] **Control flow or state mutation scattered** across helpers.
- [ ] **A suspension point** (`await`) inside invariant-dependent logic.

## P2: naming

- [ ] **Abbreviations** (`src`, `dst`, `cfg`, `msg`) beyond the trading
      vocabulary `rules/rust.md` allows (`px`, `qty`, `ts`).
- [ ] **Units or qualifiers first**: `max_latency_ms` should be
      `latency_ms_max`.
- [ ] **Related names of unequal length** that would line up in
      calculations.
- [ ] **Overloaded terms**, participles where a noun would do, helpers not
      prefixed with their caller, callbacks not last.
- [ ] **A bare number** that should be a named constant for the bound or
      protocol value it is.

## P2: scope and aliasing

- [ ] **Variables declared early or scoped wide**; dead ones left after last
      use.
- [ ] **Aliased or duplicated state** that can drift.
- [ ] **Check far from use** (POCPOU).

## P2: comments, docs and commits

- [ ] **Comments that restate the code**: replace with the why, or delete.
- [ ] **Missing rationale** on a non-obvious threshold, ordering or bound.
- [ ] **Public library items without docs**, where the language rules require
      them.
- [ ] **Non-trivial tests without a goal-and-method comment**, or tests that
      cover only valid data.
- [ ] **Commit messages that say what, not why** (flag; do not block on
      style alone).

## P3: formatting and mechanics

- [ ] **Lines over 100 columns.**
- [ ] **Multi-line `if` bodies without braces.**
- [ ] **Formatter not run** (`rustfmt`, `ruff format`, or the repo's own).
- [ ] **Compiler or linter warnings** left in touched code.

## Performance (hot-path code)

- [ ] **No back-of-envelope**: the author cannot state expected N, latency
      and throughput for the path.
- [ ] **Faster resource optimised before a slower one** (network, disk,
      memory, CPU), after weighting by frequency.
- [ ] **Batching missed**: per-event work that could be amortised.
- [ ] **Reacting directly to external events** instead of running at its own
      pace.
- [ ] **Hot loops reaching through `self`** that could be standalone
      functions over primitive arguments.
- [ ] **Control plane and data plane mixed.**
- [ ] **A performance claim without a measurement** (see the
      `systems-benchmarking` skill).
