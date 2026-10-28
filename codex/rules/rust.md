---
paths:
  - "**/*.rs"
  - "**/Cargo.toml"
---

# Rust conventions

Read this rule when a `.rs` file or `Cargo.toml` is read or edited;
agents that review Rust from a diff read this file explicitly. The baseline is
the official Rust Style Guide, the Rust API Guidelines and Google's Rust style
guide (links at the end): this file holds what they leave open, the few places
it deviates, and what a low-latency trading codebase adds. Where it is silent,
write idiomatic Rust and match the surrounding crate. In a fork (reth, op-reth,
xlayer-reth) the upstream crate's conventions win where they differ. Latency
budgets and domain rules live in the `quant-trading` skill.

Three scopes recur below. **Library code** is anything another crate or repo
depends on, forks included: the API-design rules bind. **Application code**
(the bot, a service, a tool) has one caller: the same rules are
recommendations, and simplicity wins over reuse — no trait, generic or
abstraction for a second user that does not exist. **Hot path** is market data
ingest → signal → order place/cancel, and whatever a profile shows; everything
else is cold and stays simple.

## Money and arithmetic

- Prices, quantities, balances and PnL are integer ticks/lots or a fixed-point
  decimal type in decision and accounting code; `f64` only at the wire or feed
  boundary, converted once at ingress. Arithmetic on anything from outside is
  `checked_*`, `saturating_*` or a wider intermediate (`i128` for price × qty).
- Operator overloads keep their mathematical meaning: `Qty + Qty` is fine;
  `Price * Qty` is a named method returning the notional type, never an
  `impl Mul` added as syntax sugar.

## Runtime and threading

- tokio is for I/O and cooperative multitasking, not computation. CPU-bound or
  blocking work goes to `std::thread`, `rayon` or `spawn_blocking`; a blocking
  call inside an `async fn` stalls every task on that runtime thread.
- Don't make a function `async` when it has no await point.
- Every spawned task has an owner that awaits or aborts it: a `JoinSet`, a
  scoped task, or a handle kept for shutdown, with `tokio::select!` and a
  cancellation branch for concurrent work. A `tokio::spawn` whose
  `JoinHandle` is dropped loses its panic and its error.

## Channels, locks and sharing

- Bounded channels by default, and the code says what a full channel does
  (block, drop, shed, alert). Unbounded turns backpressure into an OOM at the
  worst possible moment.
- One owner plus messages over shared state. `Arc` only for genuinely shared
  ownership, never for want of a lifetime; `Arc<Mutex<T>>` as the default way
  to share state is a smell.
- Never hold a lock across an `.await`, hold every lock for the shortest span,
  and never call unknown code (a callback, a trait method) under one. Never
  reach into a poisoned mutex with `into_inner()`: poison means an invariant
  may be broken, so propagate or restart.

## Allocation and the hot path

- On a hot path watch the hidden sources: `format!`, `to_string()`,
  `collect()`, `clone()` of an owned collection, `Box<dyn Trait>` dispatch,
  `Vec` growth. Borrow, reuse a buffer, or preallocate with capacity, and
  prove the gain the way `systems-benchmarking` prescribes.
- Off the hot path, don't pre-optimise. Know why the borrow checker
  complained before cloning; a `clone()` that keeps cold code simple is then
  the right answer.

## Errors and panics

- Pick the failure type by the contract: `Option` when the cause is obvious
  (`checked_add`, a lookup miss); `Result` when the caller must tell failure
  modes apart (I/O, a venue reply, parsing); a panic only for a bug — a
  violated invariant the caller must fix — never for runtime input.
- No `unwrap`/`expect`/`panic!`/`unreachable!` on a production path for
  anything that can fail on input: propagate with `?` and handle the error
  where something can act on it. Where the type system cannot express an
  invariant, prefer a pattern (`if let`, `let … else`) over
  check-then-unwrap, and otherwise `expect("book has a best bid after
  insert")` with the invariant as the message. Tests, benches and `build.rs`
  are exempt.
- Never turn an error into a default on a value that matters:
  `unwrap_or_default()`, `.ok()`, `let _ =` or `_ =>` on a price, quantity,
  position or exchange reply hides the failure.
- `thiserror` for library error types, `anyhow` at the binary boundary. Add
  context where an error crosses a layer:
  `.with_context(|| format!("cancel {order_id} on {venue}"))?`.
- `assert!` and `debug_assert!` carry a message saying why the invariant
  holds or what broke, with the value: `assert!(qty > 0, "fill qty must be
  positive, got {qty}")`, not a restatement of the condition.
- A panic is a crash to surface, not control flow: no `catch_unwind` for
  recovery; a task's `JoinError` is reported, never ignored.

## Types and ownership

- Newtypes for values that are easy to swap or carry a unit: `Price` vs
  `Qty`, `OrderId` vs `ClientOrderId`, venue symbol vs internal instrument. A
  type alias only abbreviates; it adds no safety.
- Parse, don't validate: wire, config and CLI input become typed structs once,
  at the boundary; the core never sees a raw string or `serde_json::Value`.
- Named fields over tuples and non-newtype tuple structs; `enum` over `bool`
  for a parameter whose meaning is not obvious at the call site
  (`Side::Buy`, `PostOnly::Yes`, not `place(true, false)`).
- `match` on a domain enum you own (order state, side, venue status, message
  type) lists every variant with no `_` arm, so a new variant fails to
  compile. On a `#[non_exhaustive]` enum from another crate, still list the
  variants you know and put the wildcard last (`Known | _ => {}`), or use
  `if let` / `let … else` when one variant matters. Mark your own enum or
  all-public-field struct `#[non_exhaustive]` only when it crosses a crate
  boundary you don't control and will grow; inside a workspace, exhaustive
  matching is the feature.
- Borrow by default, and borrow the data, not its container: `&str` not
  `&String`, `&[T]` not `&Vec<T>`, `&T` not `&Box<T>`, `Option<&T>` not
  `&Option<T>` (clippy `ptr_arg`, `borrowed_box`). Take ownership only to
  store or consume.
- Library code accepts `impl IntoIterator` and returns `impl Iterator` where
  the caller only iterates; application code takes a slice and returns a
  `Vec`. `impl Into<T>` parameters are library ergonomics, almost never
  application code.
- Private by default, `pub(crate)` for crate-internal sharing, `pub` only for
  the crate's API.
- Add explicit types where inference hides them: `.into()`, `.parse()`,
  `collect()` and long iterator chains get a type on the `let`, not a
  turbofish.

## Traits and generics

- A trait exists to be a bound (`T: Trait`, `impl Trait`, `dyn Trait`) or an
  extension (`FooExt` on a foreign type), never to organise code or for a
  swap that is not planned. Dependencies the code must inject (venue client,
  clock, random source, storage) are traits with a real second impl, the test
  fake; everything else is an inherent `impl`.
- Keep traits small and purpose-specific; several narrow traits beat one wide
  one.
- Generics (`T: Trait`) over `dyn Trait` on hot paths and in libraries; `dyn`
  when a heterogeneous collection, compile time or code size asks for it.
- `#[derive]` over a manual impl; the std trait instead of a look-alike
  method (`FromStr` not `fn from_str`, `Display` not `fn to_string`,
  `Default` when `new()` takes no arguments; clippy `should_implement_trait`,
  `inherent_to_string`, `new_without_default`, `len_without_is_empty`). Pair
  an important `From`
  impl with a named constructor; map keys get `Hash + Eq`, and `Ord` when the
  type has a total order.
- `#[must_use]` on a function or type whose result is the point (a risk-check
  verdict, a builder, a guard); `Result` already is.

## Unsafe and globals

- `unsafe` only when safe Rust cannot express it, never to get around the
  borrow checker. Encapsulate it behind a safe API in the smallest module or
  crate possible; every block carries `// SAFETY:` stating the invariant and
  how it is upheld; the PR says why safe code would not do and, when the
  reason is speed, shows the benchmark.
- No unstable features and no `#![feature]`: stay on the stable toolchain
  the repo pins.
- No code before `main()` (`ctor`-style registration) and no mutable global
  singletons; `OnceLock`/`LazyLock` only for immutable process-wide data.

## Modules and imports

- Name a file after its primary item (`order_book.rs` holds `OrderBook`);
  `mod.rs` and `lib.rs` declare and re-export, they do not implement.
- No glob imports except `use super::*` in a `#[cfg(test)]` module and
  `use Enum::*` local to a function on that enum; no preludes of our own.
  Types and traits are imported and used unqualified (`Regex`, not
  `regex::Regex`; on a clash `io::Error` or `as IoError`); free functions
  are called through their module (`mem::take(x)`, not `take(x)`).
- One module per `use` line, no nested braces (`use foo::bar::{Bar, Baz}`,
  not `use foo::{Foo, bar::Bar}`; rustfmt `imports_granularity = "Module"`).
  Import a trait inside the function that needs it unless the file uses it
  throughout.

## Naming and docs

- std conventions: `as_` (cheap borrow), `to_` (costly, borrows self),
  `into_` (consumes); `new()`, `with_foo()` for further constructors,
  `try_new()` when it returns `Result`, `from_foo()` paired with `From`;
  getters `foo()`, `foo_mut()`, `set_foo()`, `take_foo()`, `replace_foo()`;
  `FooExt` for an extension trait (clippy `wrong_self_convention`).
- No abbreviation a reader outside the team would not know (`px`, `qty`,
  `ts` are trading vocabulary; `mkt_dt_hndlr` is not). Lifetimes get names
  (`'book`, `'conn`) once more than two are in scope; a generic parameter
  takes a letter from its bound (`C: Clock`), `T` only when unbounded.
- `///` on every `pub` item saying what the code does not already say, with
  `# Panics` and `# Safety` sections where they apply; `//!` for module
  docs; `//` for implementation notes and TODOs. No comment that repeats the
  name (`/// Removes an element.`).

## Dependencies and build

- A new crate needs a reason the standard library or an existing dependency
  cannot cover; say it in the PR. Prefer versions the workspace already pins
  (`workspace = true`) and name features explicitly rather than taking the
  defaults.
- When the repo has a `deny.toml` or a `cargo audit` step, run it after
  changing `Cargo.toml` or `Cargo.lock`.
- A macro needs a reason a function, type or trait cannot cover, in this
  order of preference: `macro_rules!`, `build.rs` codegen, a proc macro.

## Style and lint

- rustfmt is the format; the Stop hook runs it on edited files.
  `#[rustfmt::skip]` only for manual alignment (a matrix, an aligned table)
  or generated code, never for taste.
- Inline format args (`format!("{err}")`, clippy `uninlined_format_args`),
  and `format!`/`write!` over `+` to join more than two strings.
- Leave touched crates clippy-clean under the repo's own lint config
  (`cargo clippy -p <crate> --all-targets`): fix the lint or `#[allow]` it on
  the item with a reason, never a wider allow (the edit guard asks).
- Keep combinator chains readable: bind a long chain to a named variable
  before the `for`, write a `for` loop when the chain mutates outside state or
  counts errors, `for_each` almost never; `any`/`all`/`find` over a
  hand-rolled loop.

## Testing

- Run tests through the named-test runner the machine-local section of the
  global AGENTS.md prescribes, never `cargo test` directly (the Bash guard
  denies it in a main checkout).
- `#[tokio::test]` for async tests; `tokio::time::pause()` to test timing
  logic without real delays; inject the clock and the random source so a
  test reads no wall clock.
- Cover the error and rejection branches, not only the happy path; an
  assertion message says what was expected, with the value.

## References

- Google Rust style guide: https://google.github.io/styleguide/rustguide.html
- Rust Style Guide: https://doc.rust-lang.org/nightly/style-guide/ ; Rust API Guidelines: https://rust-lang.github.io/api-guidelines/
- Clippy lints: https://rust-lang.github.io/rust-clippy/master/index.html ; Rustonomicon (unsafe): https://doc.rust-lang.org/nomicon/
- Tokio tutorial: https://tokio.rs/tokio/tutorial
