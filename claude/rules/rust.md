---
paths:
  - "**/*.rs"
---

# Rust essentials

Loaded automatically whenever a `.rs` file is read or edited. These are the
non-negotiables; the full conventions, with the reasoning behind them, are in
the `rust` skill — load it when writing or reviewing more than a few lines.

- Never block inside an `async fn`. CPU-bound or blocking work goes to
  `std::thread`, `rayon`, or `spawn_blocking`, not the tokio runtime.
- Channels are bounded by default; decide explicitly what a full channel does.
- Never hold a lock across an `.await`, and hold every lock for the shortest
  span possible.
- No `unwrap`/`expect`/`panic!` on production paths: propagate with `?` and
  handle errors where something can act on them. Tests are exempt.
- `thiserror` for library error types, `anyhow` at the binary boundary.
- Every `unsafe` block carries a `// SAFETY:` comment stating the invariant.
- Inline format args: `format!("{err}")`, not `format!("{}", err)`.
- On a hot path, watch the hidden allocations: `format!`, `to_string()`,
  `collect()`, `clone()` on owned collections, `Box`/`dyn` dispatch.
