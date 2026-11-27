Review this change.

**Intent:** Moves the venue's position poll off the duty loop onto a helper thread, so a slow HTTP reply no longer stalls order entry.

**File:** `src/connectivity/venue/duty.rs` (changed; line numbers on the left). Lines 5-13 and 15-16 are new.

```rust
  1 | impl Duty {
  2 |     /// Runs on the duty's own thread, which the launcher has already pinned
  3 |     /// to the duty's isolated core, where it busy-spins alone.
  4 |     pub fn run(mut self, stop: &ShutdownSignal, mut idle: IdleStrategy) -> u64 {
  5 |         let (ask_tx, ask_rx) = ring::<PollAsk>(8);
  6 |         let (answer_tx, answer_rx) = ring::<PollAnswer>(8);
  7 |         let http = self.http.clone();
  8 |         let poller = std::thread::Builder::new()
  9 |             .name(format!("{}-http", self.source))
 10 |             .spawn(move || poll_positions(http, ask_rx, answer_tx))
 11 |             .expect("http poller spawns");
 12 |         self.asks = Some(ask_tx);
 13 |         self.answers = Some(answer_rx);
 14 |         let turns = drive(&mut self, || stop.is_raised(), &mut idle);
 15 |         drop(self.asks.take());
 16 |         let _ = poller.join();
 17 |         turns
 18 |     }
 19 | }
```
