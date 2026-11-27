# Deterministic simulation in Rust

Companion to `SKILL.md`. The article's code is Java; this file is our
translation, not the article's. The general Rust conventions (injected traits
with a test fake, bounded channels, clippy-clean crates) are in
`rules/rust.md` and are not repeated here. Crate APIs change: confirm each one
against the version you pin.

## The seam as traits

- Clock, network, storage and the random source are traits the core takes as
  generic parameters (`Core<C: Clock, N: Net, S: Store, R: Rng>`), so the hot
  path pays no dynamic dispatch. The simulated implementation is the "real
  second impl" `rules/rust.md` asks for.
- Calls into a trait return at once: `send` queues, `write` and `sync` return
  an operation id. Results come back as events the loop hands to the core
  (`on_message`, `on_io_done(op, result)`), never as a callback run from an
  adapter's thread.
- Time is the tick, or a clock the loop advances. A timeout is a deadline in
  ticks stored beside the request in a waiting list; the core's tick expires
  it.
- The article needed a custom future with no blocking get and no thread-pool
  combinators. The simplest Rust equivalent is no futures in the core at all:
  a request id, a waiting-list entry and an event handler. A core that must be
  `async` has to run on a single-threaded executor the simulator controls
  (what madsim and turmoil provide), never on a multi-threaded runtime.

## The tick loop

- `trait Tick { fn tick(&mut self); }` on the network, the storage and each
  process. A world struct owns them all and ticks them in a fixed order; a
  `tick_until(pred, max_ticks)` helper returns an error when the cap is hit.
- Handlers take `&mut self` and one event, run to completion and push
  outgoing messages; no `.await`, no lock and no sleep inside the core.
- In production the same core runs on one dedicated thread. A tokio or
  socket shell owns the I/O and feeds events into the loop through a bounded
  channel; the core never sees the runtime.

## Ordered collections (rule 5)

- Where iteration order reaches a decision, the wire, persisted bytes, the
  trace or the fault log, iterate a `BTreeMap`, a sorted `Vec` or a
  fixed-seed hasher: std's `HashMap` and `HashSet` order differs between
  runs.
- The article uses insertion-ordered maps; std has none, so sorted order is
  the std answer.
- The build-time check below cannot tell a lookup from a walk. Ban the hash
  types in the core and put an item-level `#[allow]` with a reason on a map
  that is only ever looked up.

## Rule 6 at compile time

The article enforces its sixth rule (no cross-thread callbacks) at runtime: its
future records the thread that created it and rejects completion from any
other. In Rust, make the core's state `!Send` by holding an `Rc` or a
`PhantomData<Rc<()>>` marker. `std::thread::spawn` and any multi-threaded
executor's spawn require `Send`, so the compiler rejects moving the core to an
adapter's thread; the adapter has no choice but to send the loop a message.

## The build-time check (rules 1 to 5)

The article runs a static architecture test on every build. In Rust that is
clippy's `disallowed-methods` and `disallowed-types` configuration, in a
`clippy.toml` next to the core crate's `Cargo.toml` (clippy looks in the
crate's manifest directory first, then walks up). Both lints fire only when
configured and only warn by default, so deny them in the core crate:

```toml
# core/Cargo.toml
[lints.clippy]
disallowed_methods = "deny"
disallowed_types = "deny"
```

```toml
# core/clippy.toml
disallowed-methods = [
    { path = "std::time::Instant::now", reason = "rule 1: time comes from the injected clock" },
    { path = "std::time::SystemTime::now", reason = "rule 1: time comes from the injected clock" },
    { path = "std::thread::spawn", reason = "rule 3: the core runs on the loop thread" },
    { path = "std::thread::Builder::spawn", reason = "rule 3: the core runs on the loop thread" },
    { path = "std::thread::sleep", reason = "rule 3: advance ticks, never sleep" },
    { path = "std::fs::read", reason = "rule 4: storage goes through the storage trait" },
    { path = "std::fs::write", reason = "rule 4: storage goes through the storage trait" },
]
disallowed-types = [
    { path = "std::net::TcpStream", reason = "rule 4: the network goes through the network trait" },
    { path = "std::net::TcpListener", reason = "rule 4: the network goes through the network trait" },
    { path = "std::net::UdpSocket", reason = "rule 4: the network goes through the network trait" },
    { path = "std::fs::File", reason = "rule 4: storage goes through the storage trait" },
    { path = "std::collections::HashMap", reason = "rule 5: iteration order differs between runs", replacement = "std::collections::BTreeMap" },
    { path = "std::collections::HashSet", reason = "rule 5: iteration order differs between runs", replacement = "std::collections::BTreeSet" },
]
```

Every path above was checked to fire with clippy 0.1.97 (Rust 1.97); an
entry whose path does not resolve is an error unless it sets
`allow-invalid = true`. Rule 2 has no std entry: keep the runtime, network and
OS-seeded random crates out of the core crate's `[dependencies]` entirely, so
the dependency list is a check too. cargo-deny's `bans.deny` with a `wrappers`
list can hold that line across a workspace; confirm the semantics in its docs.

## Tool map

- **turmoil** (tokio-rs): runs many simulated hosts on one thread with a
  simulated network (and an unstable simulated filesystem), injecting latency,
  drops, partitions and crashes by hand (`partition`, `hold`, `repair`,
  `crash`, `bounce`) or from `Builder::rng_seed`. Fits a tokio-based system
  tested at the socket level; `Sim::step` advances one step.
- **madsim**: a tokio-like async runtime that simulates deterministically
  under `RUSTFLAGS="--cfg madsim"`, with drop-in `madsim-tokio`,
  `madsim-tonic` and other replacements. `MADSIM_TEST_SEED` replays a seed and
  `MADSIM_TEST_CHECK_DETERMINISM` runs it twice to compare. Fits a whole
  async service you do not want to restructure into ticks.
- **shuttle** (awslabs): controls thread scheduling and explores it
  randomly (`check_random`, `check_pct`), with `replay` of a failing schedule.
  Not sound, but scales. Fits the production adapters and any lock-based code
  outside the deterministic core.
- **loom** (tokio-rs): exhaustively permutes interleavings under the C11
  memory model inside `loom::model`, enabled with `--cfg loom`. Fits small
  lock-free primitives (a ring buffer, an SPSC queue), not a cluster.
- **proptest**: generated inputs with shrinking; failing cases persist under
  `proptest-regressions/` and replay first. `proptest-state-machine` drives
  a system against a reference model with generated transition sequences.
  Fits the decision core's invariants and the op generator of a simulation.
- **cargo-fuzz** and **miri** (not checked here; confirm in their own docs):
  cargo-fuzz runs coverage-guided fuzz targets over byte inputs, the right
  tool for the framing a message-level simulator skips; miri interprets tests
  to catch undefined behaviour in `unsafe` code.

## Sketch: a seeded network on a tick loop

A sketch, not a library: std only, compiled and run with the same seed twice
(identical traces) and a different seed once (a different trace). The
`main` that does that check is left out.

```rust
use std::collections::BTreeMap;
use std::marker::PhantomData;
use std::rc::Rc;

/// splitmix64: one seeded source for every decision in the run.
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    fn per_mille(&mut self, p: u64) -> bool { self.next() % 1000 < p }
    fn below(&mut self, n: u64) -> u64 { self.next() % n }
}

trait Tick { fn tick(&mut self, log: &mut Vec<String>); }

#[derive(Debug)]
struct Msg { from: u8, to: u8, id: u32 }

/// Messages wait in a queue keyed by (delivery tick, send sequence):
/// ties at one tick leave in send order, so delivery is a total order.
struct SimNet {
    now: u64, seq: u64, rng: Rng, drop_pm: u64, max_delay: u64,
    queue: BTreeMap<(u64, u64), Msg>, inbox: Vec<Msg>,
    _not_send: PhantomData<Rc<()>>, // core state stays on the loop thread
}
impl SimNet {
    fn send(&mut self, m: Msg, log: &mut Vec<String>) {
        if self.rng.per_mille(self.drop_pm) {
            log.push(format!("t={} drop {}->{} #{}", self.now, m.from, m.to, m.id));
            return;
        }
        let at = self.now + 1 + self.rng.below(self.max_delay + 1);
        self.queue.insert((at, self.seq), m);
        self.seq += 1;
    }
}
impl Tick for SimNet {
    fn tick(&mut self, log: &mut Vec<String>) {
        self.now += 1;
        while let Some(e) = self.queue.first_entry() {
            if e.key().0 > self.now { break; }
            let m = e.remove();
            log.push(format!("t={} deliver {}->{} #{}", self.now, m.from, m.to, m.id));
            self.inbox.push(m);
        }
    }
}

/// One loop, fixed order: network, then each handler runs to completion.
fn run(seed: u64, ticks: u32) -> Vec<String> {
    let mut log = Vec::new();
    let mut net = SimNet { now: 0, seq: 0, rng: Rng(seed), drop_pm: 150, max_delay: 3,
        queue: BTreeMap::new(), inbox: Vec::new(), _not_send: PhantomData };
    for id in 0..ticks {
        net.send(Msg { from: 0, to: 1, id }, &mut log); // node 0 sends a request
        net.tick(&mut log);
        for m in std::mem::take(&mut net.inbox) {
            if m.to == 1 { net.send(Msg { from: 1, to: 0, id: m.id }, &mut log); } // ack
        }
    }
    log
}
```

The determinism test is the shape every simulation suite needs:
`assert_eq!(run(seed, n), run(seed, n))` for a fixed seed, plus a check that
two seeds diverge so the generator is actually wired in.
