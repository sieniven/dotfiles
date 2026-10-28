---
paths:
  - "**/*.go"
  - "**/go.mod"
---

# Go conventions

Read this rule when a `.go` file or `go.mod` is read or edited;
agents that review Go from a diff read this file explicitly. The baseline is
Effective Go, the Go Code Review Comments wiki and Google's Go style guide
with its Decisions and Best Practices (links at the end): this file holds
what they leave open, the few places it deviates, and what this workspace
adds. In practice the Go here is the OP Stack (`op-node`, `op-geth`,
`op-batcher`, `op-conductor` and the rest under `xlayer/optimism`). These are
forks: upstream conventions win where they differ from this file, the rules
below bind new code and touched lines only, and the diff against upstream
stays as small as the change allows so the next rebase is cheap. Never
reformat, rename or re-test upstream code to match this file.

## Formatting and lint

- `gofmt` (with `-s`) is non-negotiable; the Stop hook keeps edited files
  that were already clean that way. Imports in `goimports` groups: standard
  library, then everything else, then blank `_` imports, which belong only
  in `package main` or a test that needs the side effect; no dot imports;
  rename an import only on a collision.
- Run the repo's lint config on the touched packages: `golangci-lint run`
  when the repo configures it, otherwise `go vet` and `staticcheck`. The
  checks this file leans on: vet `copylocks`, `composites`, `lostcancel`,
  `printf`, `testinggoroutine`; `errcheck`, `errorlint`, `thelper`;
  stylecheck `ST1000` (package doc), `ST1003` (initialisms), `ST1005`
  (error strings), `ST1006` (receivers).
- No line-length limit: never split a function signature, an `if`/`for`/
  `case` header or a string literal to fit; extract a named local instead
  (`if inTransaction && keysMatch`). The variable goes on the left of `==`.

## Naming

- A name is read with its package and receiver: `config.Parse`,
  `(*Config).WriteTo`, never `ParseConfig`, `widget.NewWidget` or
  `GetJobName`. A getter is the noun (`Counts()`), a doer the verb, and
  `Fetch`/`Compute` when the call can block or fail; a type suffix only to
  tell variants apart (`ParseInt64`).
- Name length grows with scope: `i`, `r`, `w` inside a few lines, words at
  file scope; no type words (`users`, not `userSlice`) and no dropped
  letters (`Sandbox`, not `Sbx`).
- Receivers are one or two letters abbreviating the type, the same on every
  method, never `this`, `self` or `_`. Initialisms keep one case throughout:
  `URL`/`url`, `ID`/`id`, `xmlAPI`, never `Url` or `Id`.
- `MaxPacketSize`, never `MAX_PACKET_SIZE` or `kMax...`; a constant is named
  for its role, not its value. Underscores only in `Test_*` names and
  `_test` packages. A package is one lowercase word that is not `util`,
  `common`, `helper` or `model`; name it for the call site.

## Comments and docs

- Every exported top-level name has a doc comment that is a full sentence
  starting with the name (`// Encode writes ...`); exactly one
  `// Package foo ...` comment per package, directly above `package`, and
  `// The foo command ...` in `main`. Field comments may be phrases.
  Comments say why, not what.
- A doc comment states what is not the default: a `Close` or `Stop` the
  caller owes, a read that mutates (an LRU), a mutator that is
  goroutine-safe, the sentinels and error types returned (and whether the
  type is a pointer), and any context behaviour that differs from "returns
  `ctx.Err()` on cancellation".

## Errors

- Never discard an error with `_` or an unchecked call: handle it or return
  it. The one exception is a call documented never to fail
  (`(*bytes.Buffer).Write`), with a comment saying so.
- A function returns `error`, never `*MyError`: a nil concrete pointer boxed
  in `error` is non-nil and the `if err != nil` passes.
- Annotate with what this layer knows and the inner error does not
  (`fmt.Errorf("derive block %d: %w", num, err)`, not `"failed: %w"`, which
  adds nothing, so return `err`). `%w` goes last so the chain reads newest
  to oldest; a sentinel that categorises the failure goes first
  (`"%w: bad header: %v"`, `ErrParse`). `%w` only where callers may
  `errors.Is`/`errors.As` the inner error, which then is part of the API;
  `%v` where a boundary (RPC, storage, a vendor SDK) should translate rather
  than leak it. Callers branch on sentinels and typed errors, never on
  `err.Error()`.
- Error strings are lowercase with no trailing punctuation, because they
  get wrapped; the log line or test message that displays them is
  capitalised.
- No in-band errors: a lookup returns `(v, ok)` or `(v, error)`, never
  `-1`, `""` or nil-versus-empty-slice as the signal. Emptiness is
  `len(s) == 0`, and an empty local is `var s []T`.
- Error first, return, then the normal path unindented; no `else` after a
  terminal `return` or `continue`; `if v, err := f(); err != nil` only when
  `v` dies within a few lines.
- A function logs an error or returns it, never both: the caller owns the
  decision and the rate. Error level is for actionable failures; no keys or
  user data in logs.
- Bad flags and config return to `main`, which exits with an actionable
  message (upstream's `log.Crit` in the forks). `panic` is for API misuse a
  caller must fix and inside `MustX` helpers, which run only at package
  init or in tests; an internal panic never crosses a package boundary.
  Never `recover` to keep a process alive: it runs on with corrupted state.

## Context

- `ctx context.Context` is the first parameter of anything that does I/O or
  can block, test helpers included (`ctx, t, ...`). Never a struct field,
  never a custom context type, never `context.Background()` below `main` or
  `init` (tests use `t.Context()`). Put a timeout on every external call.
- Cancellation returns `ctx.Err()` or an error wrapping it; a function that
  returns nil on cancel, has a separate `Stop`, or needs a context without a
  deadline says so in its doc comment, and the last is a design smell.
- Narrowing a context inside a block uses `=` with a pre-declared `cancel`,
  not `:=`, which shadows `ctx` and silently restores the unbounded one
  after the block (vet `lostcancel` catches the dropped `cancel`, not the
  shadow).

## Concurrency

- Functions are synchronous; the caller adds `go` when it wants concurrency.
  Every goroutine has a defined way to stop (a cancelled context or a closed
  channel) and an owner that waits for it (`sync.WaitGroup`, `errgroup`);
  nothing exported starts a goroutine the caller cannot stop and wait for.
  No goroutine outlives shutdown, and a lifetime that is not obvious is
  documented.
- Channel parameters and fields carry a direction (`<-chan`, `chan<-`); the
  bidirectional type stays with the owner, the only goroutine that closes it.
- Shared state is guarded by a mutex or owned by one goroutine. Never copy a
  value whose methods are on `*T` (`sync.Mutex`, `bytes.Buffer`; vet
  `copylocks`).
- Pointer receiver when the method mutates, the struct holds a mutex or a
  pointer to mutable state, or the struct is large; value receiver for
  builtins, maps, funcs, chans and small plain data; one kind per type,
  pointer when in doubt. Never take `*string` or `*io.Reader` to "save
  bytes".

## Design

- Accept interfaces, return concrete structs. Return an interface only when
  the concrete type would let callers break an invariant, when the type is
  chosen at runtime, or to break an import cycle.
- An interface needs a second real implementation, a consumer that uses two
  or three methods of a wide type, or an import cycle to break; it is
  defined where it is consumed, kept small, and unexported unless it is the
  product. A `type Service interface` with one implementation, or a wrapper
  around a generated client so tests can fake it, is a smell: test through
  the real client against a test server. No back doors for tests.
- Inject dependencies through constructors (`NewX(deps...)`). No
  package-level mutable state, registries, callback lists or lazily built
  clients: a test that replaces one leaks into the next. A package-level
  default is allowed only as a thin wrapper over the instance API, used from
  `main`, with a reset for tests. Flags live in `package main`; a library is
  configured by arguments or an options struct, never by a flag it registers
  in `init`.
- Past four or five parameters, or two adjacent of the same type, take an
  options struct (shared, mostly-set options) or variadic `Option` funcs
  (mostly-default, each documented, `WithX(v)` taking a value, not
  presence); `ctx` is never a field of either.
- Generics only when a second instantiated type exists today; an interface
  when the types share behaviour; never a generic DSL for errors or
  assertions.
- Name result parameters only to tell two same-typed results apart or to
  flag an action (`cancel func()`); no naked return past a few lines.
- Keyed fields for a struct from another package, zero-value fields omitted.
  `var x T` for a zero value filled later, `:=` with a literal when the
  contents are known; a size hint (`make([]T, 0, n)`) only when `n` is known
  or a benchmark showed the growth. `any`, not `interface{}`; `%q` for
  strings in errors, logs and test messages; `type T1 = T2` only for a
  migration; `crypto/rand` for anything secret, `math/rand` for simulation.
- Strings: `+` for two or three pieces, `fmt.Sprintf` to format,
  `fmt.Fprintf` straight to a writer, `strings.Builder` in a loop, backticks
  for a multi-line literal.

## Dependencies

- A new module needs a reason the standard library or an existing
  dependency cannot cover. Run `go mod tidy` after changing imports, and
  never bump an upstream-pinned module (e.g. the `op-geth` replace) as a
  side effect.

## Testing

- Package `testing` plus `cmp` in own code, no assertion libraries. In a
  fork, match the file's existing framework (`testify` in the OP Stack) and
  reuse upstream's helpers (`op-service/testutils`, `testlog`) before adding
  new ones.
- Table-driven with `t.Run` when the cases share one checking logic;
  disjoint logic is separate test functions. Rows use field names, omit
  zero fields, and carry a `name` that reads like an identifier (no spaces
  or `/`, which break `-run`); the failure prints the input, never
  `case #%d`.
- A failure reads `Func(%v) = %v, want %v`: function, input, got, then want,
  `%q` for strings, `cmp.Diff(want, got)` with the `(-want +got)` legend for
  large values. `t.Errorf` per mismatch so one run shows every failure;
  `t.Fatalf` only for setup and for results the next check depends on, and
  only from the test's own goroutine (a goroutine the test starts calls
  `t.Error` and returns; vet `testinggoroutine`).
- Assert errors with `errors.Is`/`errors.As` or `cmpopts.EquateErrors`,
  never on the message; `wantErr bool` when only presence matters.
- Compare whole values with `cmp.Equal`/`cmp.Diff` and `cmpopts`, not field
  by field and not `reflect.DeepEqual`; `cmp` never in production code.
  Compare parsed structures, not serialised bytes you do not own.
- A helper does setup or cleanup, takes `(ctx, t, ...)`, calls `t.Helper()`
  and `t.Fatal` on environment failure; shared validation returns an
  `error` or a `cmp.Option` for the `Test` function to report. No assertion
  helpers, and no `t` on a helper that cannot fail. Setup is scoped to the
  tests that need it (`sync.Once` when it needs no teardown), never `init`
  or a package variable; `TestMain` is the last resort.
- Doubles live in `<pkg>test`, named by kind when there is one (`Stub`,
  `Fake`) and by behaviour when there are several (`AlwaysDeclines`); a test
  local holding one says so (`spyCC`).
- Run `go test -race` on the packages you touched, not the whole monorepo,
  unless the machine-local section of the global AGENTS.md routes tests
  elsewhere.
- Cover the error branches, not only the happy path.

## References

- Google Go style guide: https://google.github.io/styleguide/go/ (guide, decisions, best-practices)
- Effective Go: https://go.dev/doc/effective_go ; Go Code Review Comments: https://go.dev/wiki/CodeReviewComments
- `cmp`: https://pkg.go.dev/github.com/google/go-cmp/cmp ; staticcheck checks: https://staticcheck.dev/docs/checks/
