Review this change.

**Intent:** Halves the memory of the per-source record counters by dropping their padding.

**File:** `src/metrics/counters.rs` (changed; line numbers on the left). Line 6 was `records: [CachePadded<AtomicU64>; MAX_SOURCES]`, and line 11 built padded cells.

```rust
  1 | use std::sync::atomic::{AtomicU64, Ordering};
  2 | 
  3 | /// One counter per source, bumped by that source's pinned feed thread on
  4 | /// every market-data record and read by the exporter on a scrape.
  5 | pub struct SourceCounters {
  6 |     records: [AtomicU64; MAX_SOURCES],
  7 | }
  8 | 
  9 | impl SourceCounters {
 10 |     pub const fn new() -> Self {
 11 |         Self { records: [const { AtomicU64::new(0) }; MAX_SOURCES] }
 12 |     }
 13 | 
 14 |     /// Called from the source's own thread, once per record.
 15 |     #[inline]
 16 |     pub fn bump(&self, source: SourceIdx) {
 17 |         self.records[source.get()].fetch_add(1, Ordering::Relaxed);
 18 |     }
 19 | 
 20 |     pub fn read(&self, source: SourceIdx) -> u64 {
 21 |         self.records[source.get()].load(Ordering::Relaxed)
 22 |     }
 23 | }
```
