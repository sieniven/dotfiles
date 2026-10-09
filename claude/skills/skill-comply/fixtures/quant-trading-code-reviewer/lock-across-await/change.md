Review this change.

**Intent:** Hedges net position after each fill by sending an IOC order on the hedge venue.

**File:** `src/hedger/position.rs` (new file; line numbers on the left)

```rust
  1 | use std::sync::Arc;
  2 | 
  3 | use tokio::sync::Mutex;
  4 | 
  5 | use crate::exchange::{HedgeClient, Side};
  6 | use crate::hedger::Position;
  7 | 
  8 | pub struct Hedger {
  9 |     position: Arc<Mutex<Position>>,
 10 |     client: HedgeClient,
 11 | }
 12 | 
 13 | impl Hedger {
 14 |     pub async fn on_fill(&self, qty: rust_decimal::Decimal) -> anyhow::Result<()> {
 15 |         let mut pos = self.position.lock().await;
 16 |         pos.apply_fill(qty);
 17 |         let net = pos.net();
 18 |         if !net.is_zero() {
 19 |             let side = if net.is_sign_positive() { Side::Sell } else { Side::Buy };
 20 |             let filled = self.client.send_ioc(side, net.abs()).await?;
 21 |             pos.apply_hedge(filled);
 22 |         }
 23 |         Ok(())
 24 |     }
 25 | }
```
