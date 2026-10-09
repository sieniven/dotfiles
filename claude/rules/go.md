---
paths:
  - "**/*.go"
  - "**/go.mod"
---

# Go conventions

Loaded automatically whenever a `.go` file or `go.mod` is read or edited —
in practice the OP Stack (`op-node`, `op-geth`, `op-batcher`, `op-conductor`
and the rest under `xlayer/optimism`). These are forks: upstream conventions
win where they differ from this file, and the diff against upstream stays as
small as the change allows so the next rebase is cheap.

## Formatting and lint

- `gofmt` is non-negotiable; the Stop hook applies it to edited files that
  were already formatted. Group imports the way `goimports` does.
- Run the repo's lint config on the touched packages: `golangci-lint run`
  when the repo configures it, otherwise `go vet`.

## Errors

- Never discard an error with `_` or an unchecked call: handle it or return
  it.
- Wrap with context when returning across a layer —
  `fmt.Errorf("derive block %d: %w", num, err)` — and compare with
  `errors.Is` / `errors.As`, never on the message string.
- `panic` only for programmer errors at startup, never on runtime input.

## Concurrency and context

- `context.Context` is the first parameter of anything that does I/O or can
  block. Pass it down, don't store it in a struct, and put a timeout on
  every external call.
- Every goroutine has a defined way to stop (a cancelled context or a closed
  channel) and an owner that waits for it (`sync.WaitGroup`, `errgroup`).
  No goroutine outlives shutdown.
- Shared state is guarded by a mutex or owned by one goroutine. Never copy a
  struct that holds a `sync.Mutex`.

## Design

- Accept interfaces, return concrete structs. Define an interface where it
  is consumed, and keep it small.
- Inject dependencies through constructors (`NewX(deps...)`); no
  package-level mutable state.

## Dependencies

- A new module needs a reason the standard library or an existing
  dependency cannot cover. Run `go mod tidy` after changing imports, and
  never bump an upstream-pinned module (e.g. the `op-geth` replace) as a
  side effect.

## Testing

- Table-driven tests with `t.Run` subtests; `t.Helper()` in helpers. Reuse
  upstream's test helpers (`op-service/testutils`, `testlog`) before adding
  new ones.
- Run `go test -race` on the packages you touched, not the whole monorepo —
  unless the machine-local section of the global CLAUDE.md routes tests
  elsewhere.
- Cover the error branches, not only the happy path.
