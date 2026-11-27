# Setting a repo up under TigerStyle

What the setup use produces, in this order: the rules block, the gate, the
ratchet, and limit values with a source. For a Rust repo, the lint, rustfmt
and cargo-deny settings are in the "Enforce it" section of [rust.md](rust.md).
Changing lint config asks first on this harness (the edit guard), and the
global CLAUDE.md asks for a plan before multi-file changes: present the plan,
then make the changes once the user approves.

## (a) The rules block

Paste into the repo's AGENTS.md or CLAUDE.md, adjusted to the language. Keep
it short: the gate enforces the mechanical rules, the block states the rest.

```markdown
## TigerStyle

This repo follows TigerStyle (load the `tigerstyle` skill). Safety, then
performance, then developer experience.

- Assert arguments, results and invariants; two per function on average,
  paired across boundaries, positive and negative space, with messages.
- Broken invariant: panic. Bad external input: typed error naming what was
  wrong. Exhaustion: typed error or backpressure. Never assert on input.
- Every loop, queue, buffer, retry and depth has a named bound whose value
  comes from a protocol, a measurement or caller policy.
- No recursion. No allocation after initialisation on hot paths.
- Functions at most 70 lines, lines at most 100 columns, warnings clean.
- Handle every error. Names: whole words, units last (`latency_ms_max`).
- Comments and commit messages say why. Tests cover invalid data too.
- `scripts/check` must print GREEN before a change is done; counts under
  `ratchet/` only ever go down.
```

## (b) The gate: `scripts/check`

One command that answers "is this change done?". Its contract:

- Runs, in order: format check, lint, tests, then any ratchet and dependency
  checks (for Rust: `cargo fmt --check`, `cargo clippy --all-targets`, the
  tests, `cargo deny check` where a `deny.toml` exists, the ratchet).
- Prints exactly one line per step: the step name and `ok` or `FAIL`, with
  the failing output after that line only on failure.
- Ends with a final line `GREEN` when every step passed, `RED` otherwise.
- Exits 0 on GREEN and non-zero on RED. It runs every step even after a
  failure, so one run shows everything that is wrong.
- Non-interactive and repeatable: no prompts, no network beyond what the
  build already needs, the same result on CI and locally. CI runs this same
  command.

On this machine tests run through the named-test runner the machine-local
section of the global CLAUDE.md prescribes, not `cargo test` directly; the
gate's test step calls that runner when it exists. TigerStyle prefers
scripts in the project's own language to shell; a short shell script that
only sequences the steps is acceptable where the repo already scripts in
shell.

## (c) Adoption by ratchet

An existing codebase will not pass on day one, and rewriting it in one change
is the wrong change. Ratchet instead:

- For each rule no lint enforces, or one a lint enforces but the codebase
  violates today, keep one count file: `ratchet/<rule>.count` holding a
  single integer, today's violation count. Examples: functions over 70 lines,
  lines over 100 columns, recursive functions, functions with no assertion,
  `let _ =` on a `Result`.
- A ratchet step in the gate recomputes each count with a mechanical counter
  (a lint run with the rule at warn, a script, a grep) and fails if any count
  is higher than its file.
- Counts are only ever lowered. A change that fixes violations lowers the
  file in the same commit; nothing raises one. Raising a count is a decision
  for the user, not for an agent to make to get to GREEN.
- When a count reaches zero, turn the rule into a hard lint (deny) and
  delete its count file.
- New code meets the rules outright; the ratchet covers what already exists.

Assertion density is the usual case for a ratchet: count functions with no
assertion and let the number fall as code is touched.

## (d) Where a limit's value comes from

Every bound needs a value, and the value needs a source, written next to the
constant:

- **A protocol**: the venue's maximum message size, the orders allowed per
  batch, the wire format's field width.
- **A measurement**: the queue depth that covers the observed burst at p99.9
  with stated headroom, from a recorded run (see `systems-benchmarking`).
- **Caller policy**: a limit the caller or operator sets in config, such as
  maximum position or orders in flight, passed in and validated at startup.

Never an arbitrary cap. `const QUEUE_MAX: usize = 1024;` with no source is a
finding; the comment says which of the three it is and where the number came
from, so the next reader can tell when it is out of date.
