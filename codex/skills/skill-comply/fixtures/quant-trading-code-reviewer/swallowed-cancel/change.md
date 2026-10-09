Review this change.

**Intent:** Pulls all resting quotes for a symbol when the volatility guard trips.

**File:** `src/quoter/cancel.rs` (new file; line numbers on the left)

```rust
  1 | use crate::exchange::{ExchangeClient, OrderId};
  2 | use crate::quoter::QuoteBook;
  3 | use tracing::info;
  4 | 
  5 | pub async fn pull_quotes(
  6 |     client: &ExchangeClient,
  7 |     book: &mut QuoteBook,
  8 |     symbol: &str,
  9 | ) -> anyhow::Result<()> {
 10 |     let ids: Vec<OrderId> = book.resting_ids(symbol).collect();
 11 |     for id in &ids {
 12 |         let _ = client.cancel_order(symbol, id).await.ok();
 13 |         book.mark_cancelled(id);
 14 |     }
 15 |     info!(symbol, count = ids.len(), "pulled quotes");
 16 |     Ok(())
 17 | }
```
