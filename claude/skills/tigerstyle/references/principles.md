# TigerStyle principles

Adapted from [fotoetienne/agent-essentials](https://github.com/fotoetienne/agent-essentials/tree/615a07f5145df00acea8da5cc0951e11462cf308/plugins/tiger-style) (MIT).

The rules of the
[canonical document](https://github.com/tigerbeetle/tigerbeetle/blob/0aeb306561365e21b97775c729bfc439f6c16d72/docs/TIGER_STYLE.md),
distilled and organised by design goal, language-agnostic. Where it says
"translate", map the rule to the language's idiom; Rust specifics are in
[rust.md](rust.md). The reconciliations in [../SKILL.md](../SKILL.md) override
anything here.

## The philosophy

- **Style is design.** Design goals in priority order: safety, performance,
  developer experience. Readability is table stakes, not the goal.
- **Simplicity is the hardest revision, not the first attempt.** It is how the
  three goals are met at once, and it takes multiple passes.
- **Zero technical debt.** Code, like steel, is cheaper to change while hot. A
  problem solved in production costs many times one solved in design, so a
  showstopper found now (a latency spike, an exponential algorithm) is fixed
  now.
- **Spend the thinking upfront.** An hour or a day of design is worth weeks or
  months in production.

## Safety

Built on NASA's
[Power of Ten](https://spinroot.com/gerard/pdf/P10.pdf) rules.

### Control flow

- **Only simple, explicit control flow. Do not use recursion**, so that every
  execution that should be bounded is bounded. Walk input-shaped data (JSON,
  trees, nested syntax) iteratively, or with an explicit depth bound that
  returns an error when reached.
- **A minimum of excellent abstractions**, and only where they make the best
  sense of the domain. Abstractions are
  [never zero cost](https://isaacfreund.com/blog/2022-05/); each one risks
  leaking.
- **Put a limit on everything.** All loops and all queues have a fixed upper
  bound, to prevent infinite loops and tail-latency spikes (fail fast). Where
  a loop cannot terminate (an event loop), assert it. Reaching a bound is a
  typed error or backpressure the caller sees, never a silent drop. Where the
  bound's value comes from is in [setup.md](setup.md).
- **Don't act directly in reaction to external events.** Run at your own pace:
  control flow stays yours, work is batched instead of context-switched per
  event, and work per period stays bounded.

### Types

- **Explicitly sized types** (`u32`, `i64`); avoid architecture-sized ones
  (`usize`, `size_t`) except where the language requires them, such as
  indexing.

### Assertions

Assertions detect programmer errors. Operating errors are expected and must be
handled; an assertion failure is unexpected, and the only correct response to
corrupt code is to crash. Assertions downgrade catastrophic correctness bugs
into liveness bugs, and multiply what fuzzing and simulation find.

- **Three kinds of failure, never mixed.** Our invariant broken: assert
  (panic). External input wrong (a venue, a peer, a file, config, a user): a
  typed error naming what was wrong. Local exhaustion (a full queue, a reached
  cap): a typed error or backpressure. Never assert on external input.
- **Assert all function arguments and return values, pre- and
  postconditions, and invariants.** A function does not operate blindly on
  data it has not checked. Average at least **two assertions per function**.
- **Pair assertions.** For each property, find two code paths to assert it:
  validate data right before it is written and again right after it is read
  back.
- **Assert the positive and the negative space**: what you expect and what
  you do not. Bugs live where data crosses the valid/invalid boundary.
- **Split compound assertions**: `assert(a); assert(b);` over
  `assert(a and b)`. Simpler to read, and the failure names the condition.
- **Assert an implication with a single-line `if`**: `if (a) assert(b)`.
- **Assert relationships between compile-time constants** to check design
  integrity before the program runs (translate: Rust `const` assertions, C++
  `static_assert`).
- **A blatantly true assertion** may replace a comment where the condition is
  critical and surprising.
- **Assertions are a safety net, not a substitute for understanding.** A
  fuzzer proves only the presence of bugs. Build a precise mental model,
  encode it as assertions, explain it in code and comments for the reviewer,
  and let simulation or fuzzing be the last line of defence.
- **Python:** `assert` is stripped under `-O`, so an invariant the code
  relies on is an explicit `raise`; see `rules/python.md`.

### Memory

- **No allocation after initialisation.** TigerBeetle's rule is absolute: all
  memory is allocated at startup. Here it binds a hot path and a deterministic
  simulated core: allocate at startup from known worst-case bounds; no
  allocate, free and reallocate afterwards. This removes unpredictable latency
  and use-after-free, and forces worst-case memory to be designed upfront.
  Translate: pre-sized collections, reused buffers, object pools, arenas.
- **Cold paths are exempt**: follow the language rule (for Rust, "off the hot
  path, don't pre-optimise").

### Scope

- **Declare variables at the smallest possible scope** and minimise how many
  are in scope at once.

### Functions

- **Hard limit of 70 lines per function.** The reason is physical: a function
  that fits on a screen versus one you scroll.
- **Inverse hourglass shape**: few parameters, a simple return type, the
  meaty logic in between.
- **Centralise control flow.** Keep the `switch`/`if` in the parent, move
  non-branching fragments to helpers:
  ["push `if`s up and `for`s down"](https://matklad.github.io/2023/11/15/push-ifs-up-and-fors-down.html).
- **Centralise state manipulation.** The parent keeps state in locals;
  helpers compute what should change and the parent applies it. Leaves stay
  pure.

### Compiler

- **All compiler warnings at the strictest setting**, from day one.

### Conditionals

- **Split compound conditions** into nested `if`/`else`, and long `else if`
  chains into `else { if { } }` trees, so every case is visible.
- **Consider whether each `if` needs a matching `else`**, so both the
  positive and negative space are handled or asserted.
- **State invariants positively**: `if (index < count)` over
  `if (index >= count)`.

### Errors

- **Handle every error.** Almost all (92%) catastrophic failures in
  distributed systems come from
  [mishandled non-fatal errors](https://www.usenix.org/system/files/conference/osdi14/osdi14-paper-yuan.pdf).
- **No silent swallowing**, and no error turned into a default, a clamp or a
  truncation on a value that matters.

### Calls

- **Pass options explicitly at the call site** instead of relying on library
  defaults, which can change underneath you.

### Motivation

- **Always say why.** Rationale shares the criteria for the decision, so the
  reader can judge the edge cases.

## Testing

- **Test exhaustively**: valid data, invalid data, and the transition as
  valid data becomes invalid. Unit tests stay; so do simulation and fuzzing.
- **Say how**: a test opens with a comment stating its goal and method.

## Performance

> "The lack of back-of-the-envelope performance sketches is the root of all
> evil."

- **Design for performance from the outset.** The 1000x wins are in design,
  precisely when you cannot yet measure.
- **Back-of-envelope sketches** over four resources (network, disk, memory,
  CPU) and two characteristics (bandwidth, latency). Be roughly right, within
  90% of the global maximum.
- **Optimise the slowest resource first** (network, disk, memory, CPU),
  after weighting by frequency: a cache miss taken often can cost more than
  one `fsync`.
- **Separate control plane from data plane.** Batching across the boundary
  keeps assertions dense without costing throughput.
- **Amortise by batching** network, disk, memory and CPU work.
- **Let the CPU sprint**: predictable, large chunks of work, no zig-zagging.
- **Be explicit; depend less on the optimiser.** Extract hot loops into
  standalone functions with primitive arguments and no `self`, so the
  compiler need not prove it can cache fields and a reader can spot redundant
  work.
- Claims of a gain are measured the way the `systems-benchmarking` skill
  prescribes.

## Developer experience

### Naming

- **Get the nouns and verbs right.** A great name gives a crisp mental model
  and shows you understand the domain.
- **`snake_case`** for functions, variables and files where the language
  allows; follow the language's own convention for types.
- **No abbreviations**, except a primitive integer used in a sort or matrix
  calculation, and the trading vocabulary `rules/rust.md` allows (`px`,
  `qty`, `ts`). Long-form flags in scripts (`--force`, not `-f`).
- **Acronyms**: TigerStyle writes `VSRState`; follow the language's
  convention where it differs (Rust writes `VsrState`).
- **Units and qualifiers last, by descending significance**:
  `latency_ms_max`, not `max_latency_ms`, so it lines up with
  `latency_ms_min` and groups with every other latency name.
- **Infuse names with meaning**: `gpa` and `arena` over `allocator` tell the
  reader who frees.
- **Related names of equal length**: `source` and `target` over `src` and
  `dest`, so `source_offset` and `target_offset` line up.
- **Prefix a helper or callback with its caller's name**: `read_sector()`
  and `read_sector_callback()`.
- **Callbacks go last** in the parameter list, as they are invoked last.
- **Order for the reader**: important things first, `main` first. When there
  is no single right order, sort alphabetically, which units-last naming makes
  useful. (Zig's fields, then types, then methods order is a Zig idiom.)
- **Don't overload a term** with two context-dependent meanings.
- **Nouns over participles**: `replica.pipeline` reads as a heading and
  composes (`config.pipeline_max`); `replica.preparing` does not.
- **Named arguments where arguments can be mixed up**: two same-typed
  arguments go in an options struct; a nullable argument is named so a `null`
  at the call site is clear. Singletons (allocator, tracer) are threaded
  positionally, most general first.

### Comments and commits

- **Descriptive commit messages** that say why. A PR description is not in
  `git blame` and does not replace one.
- **Say why** in comments. Code alone is not documentation.
- **Comments are sentences**: a space after the comment marker, a capital, a
  full stop (or a colon before what follows). An end-of-line comment may be a
  phrase.

### Cache invalidation

- **Don't duplicate variables or alias them**; state drifts out of sync.
- **Pass large arguments by reference when you don't mean a copy**
  (translate: Zig `*const` above 16 bytes, C++ `const T&`, Rust `&T`).
- **Construct large structs in place** where the language makes copies
  costly (a Zig idiom; in-place initialisation is viral to the container).
- **Calculate or check close to use.** Don't introduce a variable before it
  is needed or keep it after. A gap between place of check and place of use
  (POCPOU, cousin of TOCTOU) is where bugs hide.
- **Simpler return types reduce dimensionality** at every call site and up
  the chain: `void` over `bool` over `u64` over `?u64` over `!u64`.
- **Functions run to completion without suspending**, so precondition
  assertions hold for the whole function (translate: no `await` in the middle
  of invariant-dependent logic).
- **Beware buffer bleeds**: a buffer not fully written, its padding not
  zeroed, leaks data and breaks determinism.
- **Group allocation and its cleanup with blank lines** (before the
  allocation, after the matching `defer` or guard) so leaks are visible.

### Off-by-one

- **`index`, `count` and `size` are distinct types** with explicit
  conversions: index to count adds one, count to size multiplies by the unit.
- **Show intent in division**: exact, floor or ceiling, named (translate:
  Rust `div_euclid`, `div_ceil`), or a comment where the language has none.

### Style by the numbers

- **Run the formatter** (translate: `rustfmt`, `ruff format`, `gofmt`).
- **4 spaces of indentation** unless the project already has a convention.
- **Hard limit of 100 columns per line**: two copies side by side, nothing
  behind a horizontal scrollbar.
- **Braces on every `if`** unless it fits on one line ("goto fail;").

### Dependencies

- TigerBeetle has a zero-dependency policy. Here dependencies are not zero:
  each one is justified with its cost (what it pulls in, build time, binary
  share) and why std or an existing dependency will not do.

### Tooling

- **A small standard toolbox.** One tool known well over many known poorly.
- **Scripts in the project's primary language** rather than shell where the
  team can: portable, typed, and more likely to work on every machine.
