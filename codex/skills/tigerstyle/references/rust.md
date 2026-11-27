# TigerStyle in Rust

Adapted from [fotoetienne/agent-essentials](https://github.com/fotoetienne/agent-essentials/tree/615a07f5145df00acea8da5cc0951e11462cf308/plugins/tiger-style) (MIT) and [nanocode TIGER_STYLE.md](https://github.com/nanocodexyz/nanocode/blob/73d066e6fb3d503e4f1c54c6813cce34615c4c6a/TIGER_STYLE.md) (MIT or Apache-2.0).

How the rules in [principles.md](principles.md) land in Rust. The
language rule `~/.codex/rules/rust.md` (`rules/rust.md` below) binds
where this file differs, and each such place says so.
Rust's ownership and type system already enforce part of what TigerStyle
asserts; the rest is below, then the settings that make it a check rather
than prose.

## Assertions

- **`assert!` by default**; `debug_assert!` only where a measurement shows the
  check costs on a hot path. TigerBeetle runs its assertions in production: a
  check that vanishes in release protects nothing there.
- **Every assertion carries a message** saying why the invariant holds or what
  broke, with the value (per `rules/rust.md`, which upstream's bare
  `assert!(a)` examples miss):
  ```rust
  assert!(qty > 0, "fill qty must be positive, got {qty}");
  assert!(
      filled <= requested,
      "fill {filled} exceeds order {requested}"
  );
  // Not: assert!(qty > 0 && filled <= requested);
  ```
- **Implication**: `if is_post_only { assert!(!crosses, "post-only order
  crossed the book"); }`.
- **Compile-time**: `const _: () = assert!(HEADER_BYTES <= PAGE_BYTES);`, no
  crate needed.
- **Pair across a boundary**: assert a record before it is encoded and again
  after it is decoded; a page when committed and when loaded.
- **Negative space**: assert what must not happen too, such as a stale owner
  committing or a cancel for an order already filled.
- **Move assertions into types** where Rust can: `NonZeroU32` when zero is
  invalid, a newtype whose constructor checks its range. The runtime
  assertions that remain still average two per non-trivial function.

## Three kinds of failure

- A broken invariant of our own panics, through `assert!` or
  `expect("book has a best bid after insert")` with the invariant as the
  message (per `rules/rust.md`, which allows `expect` here).
- Wrong external input (a venue reply, a peer, a file, config, a user) is a
  typed error naming what was wrong: `thiserror` for library error types,
  `anyhow` at the binary boundary, context added where it crosses a layer.
  Never `assert!`, `unwrap` or `expect` on it.
- Local exhaustion (a full channel, a reached cap) is a typed error naming the
  bound, or backpressure the caller sees.
- None of the three hides behind truncation, clamping, `unwrap_or_default()`,
  `.ok()` or a `_ =>` fallback on a value that matters.

## Limits

- Every queue, buffer, batch, retry, concurrency level, depth and loop has a
  bound, a constant named for what it bounds with its unit last
  (`ORDERS_IN_FLIGHT_MAX`, `LATENCY_MS_MAX`). Its value comes from a protocol,
  a measurement or caller policy ([setup.md](setup.md)).
- Prefer `for i in 0..count` and `.take(LIMIT)` to an open `loop`. An
  unbounded `while let Some(x) = rx.recv().await` over an unbounded channel
  is a finding; channels are bounded and the code says what a full one does
  (per `rules/rust.md`).
- No recursion: Rust does not guarantee tail calls. Walk JSON, trees and
  nested syntax with an explicit stack, or a depth bound that returns an
  error.

## Types

- Fixed-width integers (`u32`, `i64`) for domain values; `usize` where the
  language requires it, for indexing and lengths, converted at that edge.
- Newtypes for values easy to swap or carrying a unit: `Price` and `Qty`,
  `RecordIndex` and `RecordCount`, so index-to-count and count-to-size
  conversions are explicit functions.
- Lifecycles as one enum whose variants carry only what that phase has, and
  `match` on it lists every variant with no `_` arm (per `rules/rust.md`).

## Memory

- On a hot path or in a deterministic core: size from known bounds at
  construction (`Vec::with_capacity`, `HashMap::with_capacity`), reuse buffers
  across calls (take `&mut Vec<T>`, `clear()` rather than drop), and watch the
  hidden allocations `rules/rust.md` lists (`format!`, `to_string()`,
  `collect()`, `clone()` of a collection, `Vec` growth).
- Off the hot path, don't pre-optimise (per `rules/rust.md`): a `clone()` that
  keeps cold code simple is right.
- Back an allocation change on a hot path with before and after numbers, the
  way `systems-benchmarking` prescribes.
- In-place construction through `MaybeUninit` is a Zig idiom; Rust's moves
  usually make it unnecessary, and `unsafe` for it needs the justification
  `rules/rust.md` demands.

## Control flow and function shape

- Functions of at most 70 lines; a long `match` arm becomes a helper.
- Push `if`s up and `for`s down: the parent owns the `match` and the state,
  leaves compute values over primitive inputs.
- Simple return types: `()` over `bool` over `u64` over `Option<u64>` over
  `Result<u64, E>`, and pick by contract as `rules/rust.md` describes.
- Split compound conditions into nested `if`s:
  ```rust
  if index < count {
      if !bytes.is_empty() {
          // ...
      }
  }
  // Over: if index < count && !bytes.is_empty() { ... }
  ```
- One owner per piece of state, changed through its messages or atomics; no
  hidden work in `Drop` beyond releasing what the value owns.
- No `.await` inside invariant-dependent logic: keep the core synchronous and
  await at the edges, so preconditions hold for the whole function.

## Ownership and scope

- Borrow by default (`&T`, `&[T]`, `&str`); take ownership only to store or
  consume. This is Rust's form of Zig's `*const` for large arguments.
- Don't alias state (`let a = &self.x; let b = &self.x;`): one source of
  truth. Use a block `{ ... }` to end a variable's life early; declare `let`
  as late as possible.

## Naming

- Whole words, units and qualifiers last (`latency_ms_max`, `bytes_read`),
  except the trading vocabulary `rules/rust.md` allows (`px`, `qty`, `ts`).
- Acronyms follow the Rust API Guidelines, the baseline `rules/rust.md`
  names (`VsrState`, not TigerStyle's `VSRState`); clippy's
  `upper_case_acronyms` agrees.
- A bare number in code is a constant waiting for a name.

## Calls and arithmetic

- Spell options out in a struct literal at the call site; no
  `..Default::default()` on a hot or dangerous path. An `enum` over a `bool`
  parameter (`Side::Buy`, not `place(true)`), per `rules/rust.md`.
- Show intent in division: `div_euclid`, `div_ceil` on unsigned integers,
  never an unstable method (`rules/rust.md` forbids unstable features).
- Arithmetic on anything from outside is `checked_*`, `saturating_*` or a
  wider intermediate (per `rules/rust.md`).
- Prefetch, if measured to help, through stable `core::arch` intrinsics such
  as `_mm_prefetch`, never an unstable intrinsic.

## Dependencies

Not zero (see [../SKILL.md](../SKILL.md)); each one earns its place.

- Prefer std, then a crate the workspace already has, then a small crate
  without dependencies of its own.
- Name features explicitly (`default-features = false` plus what is used) and
  take versions from the workspace (per `rules/rust.md`).
- Adding or keeping one states its cost: the packages only it brings
  (`cargo tree`), its build time (`cargo build --timings`), its binary share
  (`cargo bloat --crates`, from the separately installed cargo-bloat), and why
  std or an existing crate will not do.
- One version of each crate; a change that adds to `cargo tree --duplicates`
  says why.

## Determinism

Clock, randomness, I/O and iteration-order rules and their lints are in the
`deterministic-simulation-testing` skill.

## Style

- rustfmt, 4-space indent and 100 columns (rustfmt's defaults).
- Every warning on and clean; clippy clean under the repo's own config.

## Enforce it

A rule a check enforces is worth more than a rule in prose. The edit guard
asks before lint or format config is changed, so
setting this up is a deliberate step the user approves, done once in the setup
use, not slipped into a feature change.

`Cargo.toml` (or `[workspace.lints.rust]` and `[workspace.lints.clippy]` in
the root, with `lints.workspace = true` in each crate):

```toml
[lints.rust]
unused_must_use = "deny"           # an ignored Result fails the build

[lints.clippy]
too_many_lines = "deny"            # pedantic; threshold in clippy.toml
let_underscore_must_use = "deny"   # `let _ = fallible()` needs a reasoned allow
let_underscore_future = "deny"     # a future dropped unawaited
missing_assert_message = "deny"    # rules/rust.md: every assert says why
unwrap_used = "deny"               # use `?`, a pattern, or expect("<invariant>")
```

`clippy.toml`:

```toml
too-many-lines-threshold = 70
allow-unwrap-in-tests = true
```

- `expect_used` stays off: `rules/rust.md` allows `expect("...")` with the
  invariant as the message, and denying it would push code toward worse
  patterns.
- clippy's `too_many_lines` counts only lines that hold code (blank and
  comment-only lines are skipped), so it is a little looser than 70 physical
  lines.
- In decision or accounting modules, `#![deny(clippy::arithmetic_side_effects)]`
  at the top of that module forces checked arithmetic there without taxing the
  rest of the crate.
- `rustfmt.toml`: `max_width = 100` is the default; state it only to pin it.
  rustfmt cannot break long string literals or comments, so line width over
  100 is also a ratchet count.

`deny.toml`, run as `cargo deny check` in the gate:

```toml
[bans]
multiple-versions = "deny"         # one version of each crate
wildcards = "deny"
external-default-features = "warn" # features named explicitly
deny = [{ crate = "<crate>", reason = "<why it is banned>" }]

[sources]
unknown-registry = "deny"
unknown-git = "deny"

[advisories]
yanked = "deny"
```

A ban for which the project chose a replacement can use the shorthand
`deny = [{ crate = "openssl", use-instead = "rustls" }]`. The strictest
dependency policy is a `[bans] allow` list with a `reason` per
entry: any crate not listed, transitive ones included, is denied, so every
dependency carries its justification in the file. It is heavy to maintain;
adopt it deliberately.

Rules no lint covers (assertion density, recursion, line width in literals
and comments) go through the ratchet in [setup.md](setup.md): one count file
per rule, the gate fails if a count rises.
