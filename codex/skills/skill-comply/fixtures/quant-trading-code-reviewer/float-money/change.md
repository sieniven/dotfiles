Review this change.

**Intent:** Adds inventory-aware quote sizing: the quote size shrinks linearly as inventory approaches the position limit.

**File:** `strategy/mm/sizing.py` (new file; line numbers on the left)

```python
  1 | from decimal import Decimal
  2 | 
  3 | from tradingenginecs.orders import OrderRequest, Side
  4 | 
  5 | 
  6 | def quote_size(base_size: Decimal, inventory: Decimal, limit: Decimal) -> Decimal:
  7 |     """Shrink the quote as inventory approaches the limit."""
  8 |     if limit <= 0:
  9 |         raise ValueError("limit must be positive")
 10 |     utilisation = abs(float(inventory)) / float(limit)
 11 |     scale = max(0.0, 1.0 - utilisation)
 12 |     size = float(base_size) * scale
 13 |     return Decimal(size)
 14 | 
 15 | 
 16 | def build_bid(symbol: str, price: Decimal, base_size: Decimal, inventory: Decimal, limit: Decimal) -> OrderRequest:
 17 |     size = quote_size(base_size, inventory, limit)
 18 |     return OrderRequest(symbol=symbol, side=Side.BUY, price=price, qty=size)
```
