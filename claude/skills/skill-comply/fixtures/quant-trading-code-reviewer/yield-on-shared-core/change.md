Review this change.

**Intent:** Makes the order-entry duty friendlier to the two feed threads pinned to the same core: it now yields to them before it parks.

**File:** `src/node/launcher.rs` (changed; line numbers on the left). Line 8 was `BackoffIdle::new(10, 0, 1_000, 50_000)`; lines 4-5 were reworded to match.

```rust
  1 | /// How an order-entry duty idles on a core it shares with two feed threads,
  2 | /// each pinned to that core.
  3 | ///
  4 | /// Spins, then yields to its neighbours, then parks for up to 50 us. An
  5 | /// outbound cancel is read when the duty next runs.
  6 | const fn duty_backoff() -> BackoffIdle {
  7 |     // max_spins, max_yields, min_park_ns, max_park_ns
  8 |     BackoffIdle::new(10, 20, 1_000, 50_000)
  9 | }
 10 | 
 11 | fn duty_seat(placement: DutyPlacement) -> (CoreId, IdleStrategy) {
 12 |     match placement {
 13 |         DutyPlacement::Alone(core) => (core, IdleStrategy::BusySpin),
 14 |         DutyPlacement::TimeShared(core) => (core, IdleStrategy::Backoff(duty_backoff())),
 15 |     }
 16 | }
```
