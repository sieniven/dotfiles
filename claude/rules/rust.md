---
paths:
  - "**/*.rs"
---

# Rust conventions

Loaded automatically whenever a `.rs` file is read or edited; agents that
review Rust from a diff read this file explicitly. These are deviations from
textbook Rust defaults — where this file is silent, write idiomatic Rust. In a
fork (reth, op-reth, xlayer-reth), the upstream crate's conventions win where
they differ. Latency budgets and domain concerns live in the `quant-trading`
skill.

## Runtime and threading

- The tokio runtime is for I/O and cooperative multitasking, not computation.
  CPU-bound or blocking work goes to `std::thread`, `rayon`, or
  `spawn_blocking`.
- Never block inside an `async fn`: a blocking call on a runtime thread stalls
  every other task scheduled on it.
- Don't make a function `async` when it has no await point — sync is cheaper.

## Channels and shared state

- Bounded channels by default; decide explicitly what a full channel does.
  Unbounded turns backpressure into an OOM at the worst possible moment.
- Prefer structured concurrency — scoped tasks with a clean cancellation
  path — over detached `spawn`. `tokio::select!` for concurrent work and
  shutdown.
- Never hold a lock across an `.await`, and hold every lock for the shortest
  span possible.

## Allocation

- On a hot path, watch the hidden sources: `format!`, `to_string()`,
  `collect()`, `clone()` on owned collections, `Box`/`dyn` dispatch. Borrow,
  reuse buffers, or preallocate instead.

## Errors

- No `unwrap`/`expect`/`panic!` on production paths: propagate with `?` and
  handle errors where something can act on them. Tests are exempt.
- Never turn an error into a default on a value that matters:
  `unwrap_or_default()`, `.ok()` or `let _ =` on a price, quantity or
  exchange reply hides the failure.
- `thiserror` for library error types, `anyhow` at the binary boundary. Add
  context where an error crosses a layer:
  `.with_context(|| format!("cancel {order_id} on {venue}"))?`.

## Types and ownership

- Newtypes for values that are easy to swap: `Price` vs `Qty`, `OrderId` vs
  `ClientOrderId`, venue symbol vs internal instrument. Parse, don't
  validate: turn wire and config input into typed structs once, at the
  boundary.
- `match` exhaustively on domain enums — order state, side, venue status,
  message type — with no `_` arm, so a new variant fails to compile instead
  of falling through.
- Borrow by default: take `&str`, `&[T]` or `&T`; take ownership only to
  store or consume. Never `.clone()` to quiet the borrow checker without
  knowing why it complained.
- Private by default, `pub(crate)` for crate-internal sharing, `pub` only for
  the crate's API.

## Unsafe

- Avoid `unsafe`. Every `unsafe` block carries a `// SAFETY:` comment stating
  the invariant and how it is upheld; never use it to get around the borrow
  checker.

## Architecture

- Depend on traits, not concrete types, and inject dependencies explicitly.
  No global singletons or implicit construction.
- Keep traits small and purpose-specific — several narrow traits beat one
  wide one.

## Dependencies

- A new crate needs a reason the standard library or an existing dependency
  cannot cover; say it in the PR. Prefer versions the workspace already pins.
- When the repo has a `deny.toml` or a `cargo audit` step, run it after
  changing `Cargo.toml` or `Cargo.lock`.

## Style

- Inline format args: `format!("{err}")`, not `format!("{}", err)` — clippy's
  `uninlined_format_args`, for every formatting macro.
- Leave touched crates clippy-clean under the repo's own lint config
  (`cargo clippy -p <crate> --all-targets`).

## Testing

- Run tests through the named-test runner the machine-local section of the
  global CLAUDE.md prescribes, never `cargo test` directly.
- `#[tokio::test]` for async tests; `tokio::time::pause()` to test timing
  logic without real delays.
- Cover the error and rejection branches, not only the happy path.
