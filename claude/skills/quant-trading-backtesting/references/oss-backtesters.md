# hftbacktest and NautilusTrader as reference implementations

Two open-source backtesters checked out under `~/dev/oss/` (`hftbacktest`,
`nautilus_trader`) that implement the models the skill describes. Read them
for the shape of a latency or queue model before writing one, and to say
precisely what the platform lacks. Facts below are from their docs and
source at the time of writing; the checkout wins where it differs.

## hftbacktest

Market-data replay in Rust with Python bindings through Numba. Its own
framing: the order cannot change the simulated market, no impact is
modelled, so the order must be small, and the live run is where the
simulator is corrected from. Features: tick-by-tick simulation, book
reconstruction from L2 market-by-price and L3 market-by-order feeds, feed
and order latency through provided or custom models, queue-aware fills,
multi-asset and multi-exchange runs, and the same algorithm code deployable
live (Rust, Binance Futures and Bybit).

**Latencies.** Feed latency is carried by the two timestamps on each event.
Order entry latency is send to matching engine; order response latency is
matching engine to local receipt, and a fill notification pays it too. The
model answers both per order:

```rust
pub trait LatencyModel {
    fn entry(&mut self, timestamp: i64, order: &Order) -> i64;
    fn response(&mut self, timestamp: i64, order: &Order) -> i64;
}
```

Provided: `ConstantLatency` (fixed entry and response);
`IntpOrderLatency`, which interpolates a recorded series with columns
`req_ts, exch_ts, resp_ts` and is the most accurate when the series is
fine-grained, collected by submitting unexecutable orders on a schedule; a
`latency_offset` that shifts entry and response when the feed was recorded
at a different site from where the strategy runs; and a recipe for
synthesising order latency from feed latency when no live series exists.
Units follow the data's timestamps, nanoseconds by convention.

**Exchange models.** `NoPartialFillExchange` (default): a resting buy fills
in full when its price is at or above the best ask, above a sell trade's
price, or equal to it while at the head of the queue (mirror for sells);
takers fill in full at the best regardless of displayed size.
`PartialFillExchange`: the same crossing rules, partial fills by the
remaining trade quantity at the head, and takers walk the book's quantity,
though the book still does not deplete.

**Queue models on L2.** `RiskAdverseQueueModel`: the position advances only
on trades at the price, every cancel is behind you. `ProbQueueModel` with
`PowerProbQueueFunc`, `PowerProbQueueFunc2`, `PowerProbQueueFunc3`,
`LogProbQueueFunc` and `LogProbQueueFunc2`: a size decrease at the level is
split before and after the order by `f(x)` of its relative position, with
`f(0) = 0` and `f(1) = 1`; `log(1 + x)` makes the split depend on the
level's total size. Trade quantity is subtracted from the book decrease
before the model sees it, to avoid double counting. The docs' own advice is
to tune the power family until simulated results align with live. The
trait gives the model per-order hooks (`new_order`, `trade`, and depth
change) on an `Order` it may annotate.

**L3.** `L3QueueModel` tracks backtest orders among the feed's orders per
side and price (`contains_backtest_order`, best-bid and best-ask update
hooks returning the orders they fill); `L3FIFOQueueModel` keeps a FIFO per
`(side, price)` holding both market-feed and backtest orders, so position
is exact by order id. The Python API exposes `l3_fifo_queue_model()`, and
the L3 tutorial builds L2 from L3 to compare the two readings.

**Live against backtest.** Plot equity, position, signal and order prices
from both on one chart first. Two causes account for most gaps: latency
(collect your own feed and order latency; verify a vendor's feed latency
matches yours) and the queue model (tune it). Lowering latency artificially
prices an infrastructure or tier upgrade. Impact grows with size and with
taking liquidity; start small, align, then grow while comparing.

**Accelerated mode** runs the loop once per iteration by ignoring queue
fills and response latency: screening only, it cannot see a cancel-fill
race.

## NautilusTrader

An event-driven platform whose backtest venue is configured by `book_type`:
`L1_MBP`, `L2_MBP` or `L3_MBO`. The type decides what updates the book and
what triggers matching: quotes and bars update an L1 book only, deltas
update L2 and L3 only, trades trigger matching on all three. Granularity
cannot be generated upward, and an L2 or L3 venue fed only quotes or bars
never fills an order.

**Fill models.** `DefaultFillModel(prob_fill_on_limit=1.0,
prob_slippage=0.0, random_seed=None)`. `prob_fill_on_limit` is the chance a
limit order fills when touched but not crossed (crossing is a separate
matching condition); `prob_slippage` moves an L1 fill one tick against the
order and does not apply to L2 or L3, where the book sets the price. A
family of synthetic-book models supplies liquidity an L1 feed lacks
(`BestPriceFillModel`, `OneTickSlippageFillModel`,
`ProbabilisticFillModel`, `TwoTierFillModel`, `ThreeTierFillModel`,
`LimitOrderPartialFillModel`, `SizeAwareFillModel`,
`CompetitionAwareFillModel`, `VolumeSensitiveFillModel`,
`MarketHoursFillModel`), with tier sizes in instrument units to check
against the instrument's scale. A custom model implements
`is_limit_filled`, `is_slipped`, optionally `fill_limit_inside_spread` and
`get_orderbook_for_fill_simulation`.

**Book immutability.** Historical depth does not change after a simulated
fill, so with `liquidity_consumption=False` one displayed size can fill
several simulated orders in an iteration; `liquidity_consumption=True`
tracks consumed size per level until fresh data. `queue_position=True`
with book and trade data tracks the displayed queue ahead of an order;
trade-driven fills share the print's size instead of each consuming it
whole; a triggered order accounts for the depth the triggering trade
already took. Trade-driven fills are called opportunistic: a print proves
liquidity existed for a moment.

**Latency.** With a `LatencyModel`, commands enter the venue's inflight
queue stamped with their arrival time and settle when the engine reaches
it; `on_stop` commands pay the same latency, and shutdown advances the clock
to the last inflight arrival so they still settle. Trade ids are
deterministic (an FNV-1a hash of venue, raw id and `ts_init`, plus a
counter), so reruns match.

**Matching by order type on L2 and L3.** `MARKET` walks crossed levels as a
taker; `LIMIT` takes crossed levels or rests at its price as a maker;
`MARKET_TO_LIMIT` walks then rests the remainder at its first fill price;
stop and if-touched orders trigger first, then follow the market or limit
rule.

## Sources

- hftbacktest docs, local checkout `~/dev/oss/hftbacktest/docs/`:
  `latency_models.rst`, `order_fill.rst`,
  `debugging_backtesting_and_live_discrepancies.rst`; source
  `hftbacktest/src/backtest/models/latency.rs` and `queue.rs`;
  <https://hftbacktest.readthedocs.io/en/latest/reference/initialization.html>,
  <https://hftbacktest.readthedocs.io/en/latest/tutorials/Level-3%20Backtesting.html>,
  <https://hftbacktest.readthedocs.io/en/latest/tutorials/Probability%20Queue%20Models.html>,
  <https://hftbacktest.readthedocs.io/en/latest/tutorials/Accelerated%20Backtesting.html>.
- NautilusTrader docs, local checkout
  `~/dev/oss/nautilus_trader/docs/concepts/backtesting/`: `fill-models.md`,
  `fill-prices-and-matching.md`, `data-and-venues.md`, `execution-flow.md`;
  <https://nautilustrader.io/docs/latest/concepts/backtesting/data-and-venues/>.
- Queue-position estimation background:
  <https://rigtorp.se/2013/06/08/estimating-order-queue-position.html>,
  <https://moallemi.com/ciamac/papers/queue-value-2016.pdf>.
- Markouts: <https://kx.com/glossary/what-is-markout-and-how-is-it-calculated/>.
