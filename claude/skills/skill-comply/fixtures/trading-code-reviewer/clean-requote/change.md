Review this change.

**Intent:** Only requote when the fair price moves by at least `min_move_ticks`, to save rate-limit budget.

**File:** `src/quoter/requote.rs` (new file; line numbers on the left)

```rust
  1 | use rust_decimal::Decimal;
  2 | 
  3 | /// Decides whether a resting quote should be replaced after a fair-price update.
  4 | pub struct RequoteRule {
  5 |     tick_size: Decimal,
  6 |     min_move_ticks: u32,
  7 | }
  8 | 
  9 | impl RequoteRule {
 10 |     pub fn new(tick_size: Decimal, min_move_ticks: u32) -> Self {
 11 |         assert!(tick_size > Decimal::ZERO, "tick size must be positive");
 12 |         Self { tick_size, min_move_ticks }
 13 |     }
 14 | 
 15 |     pub fn should_requote(&self, resting: Decimal, fair: Decimal) -> bool {
 16 |         let moved_ticks = ((fair - resting).abs() / self.tick_size).floor();
 17 |         moved_ticks >= Decimal::from(self.min_move_ticks)
 18 |     }
 19 | }
 20 | 
 21 | #[cfg(test)]
 22 | mod tests {
 23 |     use super::*;
 24 |     use rust_decimal_macros::dec;
 25 | 
 26 |     #[test]
 27 |     fn requotes_only_past_threshold() {
 28 |         let rule = RequoteRule::new(dec!(0.5), 2);
 29 |         assert!(!rule.should_requote(dec!(100.0), dec!(100.5)));
 30 |         assert!(rule.should_requote(dec!(100.0), dec!(101.0)));
 31 |         assert!(rule.should_requote(dec!(100.0), dec!(99.0)));
 32 |     }
 33 | }
```
