---
name: rust
description: Rust conventions — tokio vs OS threads, bounded channels and lock discipline, hidden allocation sources, error handling with thiserror/anyhow, trait-based dependency injection, unsafe rules, async testing. Use when writing, reviewing, or debugging Rust.
---

# Rust conventions

Deviations from textbook Rust defaults. Where this file is silent, write
idiomatic Rust. Latency budgets and domain concerns live in the `trading` skill.

## Runtime and threading

- The tokio runtime is for I/O and cooperative multitasking, not computation.
  CPU-bound work goes to `std::thread`, `rayon`, or `spawn_blocking`: parallel
  data processing, long-running computation that doesn't yield, and blocking
  calls with no async equivalent.
- Never block inside an `async fn`. A blocking call on a runtime thread stalls
  every other task scheduled on it.
- Don't make something `async` that has no await point — sync is cheaper.

## Channels and shared state

- Bounded channels by default. Unbounded turns backpressure into an OOM at the
  worst possible moment. Decide explicitly what a full channel does.
- Prefer structured concurrency — scoped tasks with clean cancellation paths —
  over detached `spawn`. `tokio::select!` for concurrent work and shutdown.
- Hold locks for the shortest span possible, and never across an `.await`.

## Allocation

- Where allocation matters, watch the hidden sources: `format!`, `to_string()`,
  `collect()`, `clone()` on owned collections, and `Box`/`dyn` dispatch. Borrow,
  reuse buffers, or preallocate instead.

## Errors and unsafe

- No `unwrap`/`expect`/`panic!` in production paths — propagate with `?` and
  handle errors where something can act on them. Tests are exempt.
- `thiserror` for library error types; `anyhow` at the binary boundary.
- Avoid `unsafe`. Where unavoidable, document it with a `// SAFETY:` comment
  explaining how the invariant is upheld.

## Architecture

- Depend on traits, not concrete types, and inject dependencies explicitly. No
  global singletons or implicit construction.
- Keep traits small and purpose-specific — several narrow traits beat one wide
  one.

## Style

- Inline format args: `format!("{err}")`, not `format!("{}", err)`. Clippy's
  `uninlined_format_args`; applies to every formatting macro.

## Testing

- `#[tokio::test]` for async tests.
- `tokio::time::pause()` to test timing logic without real delays.
