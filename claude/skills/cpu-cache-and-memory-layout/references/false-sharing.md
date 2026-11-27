# False sharing, and sharing done on purpose

Companion to `SKILL.md`. How a contended line behaves, how to find one,
and the layouts that avoid it.

## The mechanism

A cache line is in one of a few states per core: modified here,
exclusive here, shared with others, or invalid. A store needs the line
modified or exclusive. If another core has it, the storing core asks for
ownership, the other core's copy is invalidated, and its next access
misses and fetches the line back from the first core. Two cores that
alternate writes to one line pass it back and forth on every write. Each
pass costs tens of nanoseconds, against about one for an uncontended
store.

It does not matter whether the two cores touch the same bytes. The unit
is the line.

## Finding it

- **Symptom**: a thread's latency or throughput worsens when another
  thread is busy, though they share no lock and no variable; instructions
  per cycle fall with no change in the instruction count; scaling to more
  threads makes each slower.
- **`perf c2c`** samples loads and stores with their data addresses and
  reports the lines with the most hits on a line modified by another core
  (HITM), with the offsets within the line and the code that touched
  each. Two offsets written from two threads on one line is the
  signature. It relies on precise memory sampling: load-latency and
  precise-store events on Intel, IBS on AMD (not available on Zen 3), SPE
  on Arm with kernel support. In most guests that sampling is not
  exposed.
- **Without it**: move the suspect field onto its own padded line and
  measure. A fix that works is the proof.
- **By reading**: list every field written after start-up, and the thread
  that writes it. Any two writers, or a writer and a hot reader, sharing a
  struct or adjacent array slots are suspects until their offsets say
  otherwise.

## Where it hides

| Place | Why |
| --- | --- |
| A ring's head and tail declared side by side | producer writes one, consumer the other |
| Counters in a `[AtomicU64; N]` indexed by thread or source | adjacent slots, eight to a line |
| A struct holding a flag one thread publishes beside state another thread updates | one line, two writers |
| Small heap objects allocated together by different threads' owners | the allocator packs them into one line |
| A `Vec<Mutex<T>>` or array of small locks | neighbouring locks share lines |
| An `Arc`'s counts beside its data | every clone writes the line readers load |
| A read-mostly table with a statistics field in its header | every lookup misses after each update |
| The first and last elements of adjacent per-thread buffers | the boundary line belongs to both |

## Layouts that work

**A cell one thread publishes and others read.** One atomic alone on a
padded line. The writer's store invalidates readers once per change, not
once per read. Readers on the hot path use a relaxed load.

**A single-producer, single-consumer ring.**

- The producer's index and the consumer's index on separate padded lines.
- Each side keeps a private, unshared copy of the other side's index and
  re-reads the shared one only when its copy says the ring is full (for
  the producer) or empty (for the consumer). In steady flow each side then
  touches the other's line rarely.
- The slots are written by one side and read by the other: that transfer
  is the message itself and cannot be removed, only batched. Slots sized
  and aligned to whole lines keep one message from straddling two
  transfers.
- Publishing the index once per burst, rather than once per record, makes
  a burst cost one transfer of the index line.

**Per-thread or per-source counters.** One padded slot each, summed by
the reader. The reader's occasional load costs the writer a miss on its
next increment; a scrape every few seconds is nothing, a reader in a loop
is a false-sharing source of its own.

**A record read by another process through a shared mapping.** A
generation word and the body laid out by line, so a reader's copy touches
whole lines the writer has finished with, and the writer's next record
goes to lines the reader is not on.

## How much to pad

- 64 bytes separates lines on current x86-64 and most aarch64 servers.
- 128 bytes also defeats the adjacent-line prefetcher on x86-64 and
  covers CPUs whose lines are 128 bytes; it is what crossbeam's
  `CachePadded` uses there.
- Read `coherency_line_size` on the host when a layout depends on the
  exact number, and pin the choice with an assertion on the type's
  alignment.
- A padded value costs its padding in cache capacity. Thousands of padded
  cells are megabytes that push other data out of L2.

## Testing a fix

1. A bench with both threads running, pinned to the cores they will use,
   since the effect vanishes on one thread.
2. Before and after from the same session, interleaved.
3. The same-thread number beside it as the floor.
4. A compile-time assertion on the offsets, so a later field does not
   move the layout back.

## Sources

`tools/perf/Documentation/perf-c2c.txt` in the kernel tree;
`crossbeam-utils/src/cache_padded.rs` (the per-architecture alignments and
their reasons); the CPU vendors' optimisation manuals for prefetcher
behaviour.
