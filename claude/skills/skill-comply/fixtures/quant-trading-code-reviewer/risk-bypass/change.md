Review this change.

**Intent:** Adds a fast path for latency-sensitive arbitrage legs that skips the slower position snapshot refresh.

**File:** `strategy/arb/executor.py` (new file; line numbers on the left)

```python
  1 | from decimal import Decimal
  2 | 
  3 | from tradingenginecs.risk import PreTradeRisk
  4 | from tradingenginecs.orders import OrderRequest
  5 | 
  6 | 
  7 | class ArbExecutor:
  8 |     def __init__(self, gateway, risk: PreTradeRisk):
  9 |         self.gateway = gateway
 10 |         self.risk = risk
 11 | 
 12 |     def send_leg(self, order: OrderRequest, fast_path: bool = False) -> str:
 13 |         if fast_path:
 14 |             return self.gateway.place(order)
 15 |         self.risk.refresh_positions()
 16 |         decision = self.risk.check(order)
 17 |         if not decision.approved:
 18 |             raise RuntimeError(f"risk rejected: {decision.reason}")
 19 |         return self.gateway.place(order)
 20 | 
 21 |     def hedge_notional(self, order: OrderRequest) -> Decimal:
 22 |         return order.price * order.qty
```
