Review this change.

**Intent:** Loads per-symbol quoting parameters from TOML at startup and logs a summary.

**File:** `src/config/load.rs` (new file; line numbers on the left)

```rust
  1 | use std::collections::HashMap;
  2 | use std::path::Path;
  3 | 
  4 | use anyhow::Context;
  5 | use serde::Deserialize;
  6 | use tracing::info;
  7 | 
  8 | #[derive(Debug, Deserialize)]
  9 | pub struct SymbolParams {
 10 |     pub spread_bps: u32,
 11 |     pub max_position: rust_decimal::Decimal,
 12 | }
 13 | 
 14 | pub fn load(path: &Path) -> anyhow::Result<HashMap<String, SymbolParams>> {
 15 |     let raw = std::fs::read_to_string(path)
 16 |         .with_context(|| format!("reading {}", path.display()))?;
 17 |     let params: HashMap<String, SymbolParams> =
 18 |         toml::from_str(&raw).with_context(|| format!("parsing {}", path.display()))?;
 19 |     let summary: Vec<String> = params.keys().map(|s| s.to_string()).collect();
 20 |     info!(symbols = %summary.join(","), "loaded quoting params");
 21 |     Ok(params)
 22 | }
```
