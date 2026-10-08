# Flashblocks protocol, reorg protection and state root

Wire protocol, zero-reorg protection (broadcast ordering, persistence and replay, follower cache), supported RPC APIs, and state root computation modes.

## Contents

- [Flashblocks Wire Protocol](#flashblocks-wire-protocol)
  - [`XLayerFlashblockMessage` (builder → RPC node)](#xlayerflashblockmessage-builder--rpc-node)
  - [`OpFlashblockPayload` (from `op-alloy-rpc-types-engine`)](#opflashblockpayload-from-op-alloy-rpc-types-engine)
  - [P2P Protocol](#p2p-protocol)
- [Zero-Reorg Protection](#zero-reorg-protection)
  - [Broadcast Ordering (P2P Before WebSocket)](#broadcast-ordering-p2p-before-websocket)
  - [Builder-Side Persistence & Replay (`FlashblockPayloadsCache`)](#builder-side-persistence--replay-flashblockpayloadscache)
  - [RPC Node Persistence (`persist.rs`)](#rpc-node-persistence-persistrs)
  - [Follower Sequencer P2P Cache](#follower-sequencer-p2p-cache)
  - [Full-Payload P2P Mode](#full-payload-p2p-mode)
  - [Protection Guarantees](#protection-guarantees)
  - [Reorg Risk Caveat](#reorg-risk-caveat)
- [Supported Flashblocks Eth RPC APIs](#supported-flashblocks-eth-rpc-apis)
- [State Root Computation](#state-root-computation)
  - [Builder Side (`xlayer-builder`) — Three Modes](#builder-side-xlayer-builder--three-modes)
  - [RPC Node Validator Side (`xlayer-flashblocks`) — Three Strategies](#rpc-node-validator-side-xlayer-flashblocks--three-strategies)

## Flashblocks Wire Protocol

### `XLayerFlashblockMessage` (builder → RPC node)

Enum with two variants, sent via WS stream and P2P:
- **`Payload(XLayerFlashblockPayload)`** — wraps `OpFlashblockPayload` delta with `target_index` (allows RPC node to know sequence end optimistically)
- **`End(XLayerFlashblockEnd)`** — explicit end-of-sequence signal sent on payload resolution. Contains `payload_id`. Triggers SR computation and pending→confirm promotion on RPC node.

### `OpFlashblockPayload` (from `op-alloy-rpc-types-engine`)

Wire format for each flashblock delta:
- `payload_id: PayloadId`
- `index: u64` — 0 = base/fallback, 1..N = incremental flashblocks
- `base: Option<OpFlashblockPayloadBase>` — only at index 0: `parent_hash`, `fee_recipient`, `prev_randao`, `block_number`, `gas_limit`, `timestamp`, `extra_data`, `base_fee_per_gas`
- `diff: OpFlashblockPayloadDelta` — `state_root`, `receipts_root`, `logs_bloom`, `gas_used`, `block_hash`, `transactions`, `withdrawals`, `withdrawals_root`, `blob_gas_used`
- `metadata: OpFlashblockPayloadMetadata` — `receipts` (by tx hash), `new_account_balances`, `block_number`

### P2P Protocol

Protocol ID: `/flashblocks/2.0.0`. Transport: TCP + noise + yamux. Discovery: mDNS + Kademlia. Per-(peer, protocol) deduplication. Non-blocking `open_stream` with connection retry.

---

## Zero-Reorg Protection

The flashblocks system provides zero-reorg guarantees for RPC node subscribers through ordered broadcast, persistence, and replay mechanisms. The protection operates at the application layer.

### Broadcast Ordering (P2P Before WebSocket)

The builder enforces strict ordering: P2P gossip to follower sequencers completes BEFORE WebSocket broadcast to RPC nodes. This ensures atomicity of flashblocks replay during sequencer switches/failures.

**Flow in `broadcast/mod.rs` (`Node::run()`):**
1. Builder produces `XLayerFlashblockMessage` → sends to `FlashblocksPayloadHandler` via channel
2. Handler forwards to P2P broadcast node via `p2p_tx.send(Message::from_flashblock_payload(payload))`
3. Broadcast node's message loop:
   - `outgoing_streams_handler.broadcast_message(message.clone()).await` — **blocking wait** sends to all connected P2P peers concurrently, awaits ALL TCP sends
   - Only after P2P completes: `ws_pub.publish(fb_payload)` — broadcasts to WebSocket subscribers (RPC nodes)
   - Note websocket publish below only runs after all peer sends have resolved. TCP send success means the kernel accepted the bytes into the send buffer, however this means that networking layer failures are swallowed — only serialization errors are propagated. This design is intentional and the reorg risk the builder trades off for lower latency

**Failed P2P peers:** On send failure, peers are removed from stream map and pushed to retry queue. `open_stream` retries immediately if TCP connection is still alive, otherwise reconnects with 1s retry interval.

### Builder-Side Persistence & Replay (`FlashblockPayloadsCache`)

**Location:** `crates/builder/src/flashblocks/utils/cache.rs`

`FlashblockPayloadsCache` stores the current pending block's flashblock payloads sequence, enabling transaction replay on builder failover (conductor-driven sequencer switch).

**Data structure:**
```rust
struct FlashblockPayloadsSequence {
    payload_id: PayloadId,
    parent_hash: Option<B256>,
    payloads: Vec<OpFlashblockPayload>,
}
```

**Cache operations:**
- `new(datadir)` — loads persisted sequence from `{datadir}/flashblocks/pending_sequence.json` on startup (if file exists)
- `add_flashblock_payload(payload)` — appends to current sequence if same `payload_id`, otherwise replaces entire cache (new block)
- `persist()` — atomic write: serialize → write to temp file → rename (crash-safe)
- `get_flashblocks_sequence_txs(parent_hash)` — retrieves cached transaction sequence for replay. Validates: parent_hash match, sequential indexes (no gaps), skips base index 0 (sequencer deposits)

**Replay flow on builder startup** (`flashblocks/builder.rs`):
1. Builder checks `p2p_cache.get_flashblocks_sequence_txs(parent_hash)` — matches against current FCU parent
2. Cache hit with non-empty txs → calls `ctx.execute_cached_flashblocks_transactions(&mut info, &mut state, cached_txs)`
3. Replays all cached transactions via EVM execution, validates DA limits, tracks metrics
4. Sets `rebuild_external_payload = true` → skips fresh transaction pool processing, resolves payload immediately
5. On replay errors, resolves payload up to the point of failure (partial replay is acceptable)

**Config:** `--flashblocks.replay-from-persistence-file` (env: `FLASHBLOCKS_REPLAY_FROM_PERSISTENCE_FILE`, default: false)

### RPC Node Persistence (`persist.rs`)

**Location:** `crates/flashblocks/src/persist.rs`

The RPC node independently persists received flashblocks to disk, enabling recovery from restarts.

**`handle_persistence(rx, datadir)`:**
1. Creates `FlashblockPayloadsCache::new(Some(datadir))` — loads any existing persisted sequence on startup
2. Receives `XLayerFlashblockMessage` via broadcast channel (subscribes to `received_flashblocks_tx`)
3. On `Payload` variant: adds to cache, marks dirty
4. Every 5 seconds (flush interval): if dirty, calls `cache.persist()` (atomic write)
5. On shutdown: final flush of dirty state

**`handle_relay_flashblocks(rx, ws_pub)`:**
- Runs in parallel with persistence
- Forwards all received flashblocks directly to downstream WebSocket subscribers

Both tasks spawned as `spawn_critical_task` from `FlashblocksRpcService::spawn_persistence()`.

**Persistence file:** `{datadir}/flashblocks/pending_sequence.json`

### Follower Sequencer P2P Cache

On the follower sequencer (managed by `op-conductor`), the `FlashblocksPayloadHandler` receives flashblocks via P2P from the leader:

1. `Message::OpFlashblockPayload(fb_payload)` received from P2P
2. If `Payload` variant: `p2p_cache.add_flashblock_payload(payload.inner.clone())` — caches for replay
3. Then `ws_pub.publish(&fb_payload)` — forwards to local WS subscribers

On conductor-driven failover:
1. New leader's builder starts with `replay_from_persistence_file = true`
2. `FlashblockPayloadsCache::new(Some(datadir))` loads cached sequence from previous leader's gossip
3. On next FCU, builder checks `get_flashblocks_sequence_txs(parent_hash)` → cache hit → replays exact same transactions
4. Ensures RPC nodes see consistent transaction ordering across leader switches

### Full-Payload P2P Mode

For even stronger consistency, the builder supports sending complete built payloads (not just deltas) via P2P:
- `--flashblocks.p2p_send_full_payload` — leader sends `Message::OpBuiltPayload` containing the fully assembled block
- `--flashblocks.p2p_process_full_payload` — follower executes received full payloads via `execute_built_payload()`:
  1. Validates header against parent (consensus rules)
  2. Re-executes all transactions via EVM
  3. Verifies block hash matches
  4. Sends `Events::BuiltPayload` to pre-warm engine tree

### Protection Guarantees

| Guarantee | Mechanism |
|---|---|
| Lost flashblocks recovered from disk | Persistence on both builder and RPC node |
| Same tx order across builder failover | P2P cache replay via `execute_cached_flashblocks_transactions` |
| P2P followers see blocks before RPC clients | Ordered broadcast: P2P → then WS |
| Invalid sequences rejected | Sequential index validation, parent_hash match |
| Crash-safe persistence | Atomic temp-file → rename pattern |
| Partial replay tolerance | Replay errors resolve payload up to failure point |

### Reorg Risk Caveat

The zero-reorg protection operates at the **application layer**. If P2P broadcast fails at the transport layer (TCP send succeeds into kernel buffer but delivery fails), the blocking broadcast may appear successful while the follower never received the message. This is a deliberate trade-off for lower latency — builder switches are rare events.

---

## Supported Flashblocks Eth RPC APIs

The flashblocks RPC layer overrides all eth JSON-RPC APIs to support the flashblocks state cache + underlying canonical provider:

**Block APIs:**
- `eth_blockNumber`, `eth_getBlockByNumber`, `eth_getBlockByHash`
- `eth_getBlockReceipts`
- `eth_getBlockTransactionCountByNumber`, `eth_getBlockTransactionCountByHash`

**Transaction APIs:**
- `eth_getTransactionByHash`, `eth_getRawTransactionByHash`
- `eth_getTransactionReceipt`
- `eth_getTransactionByBlockHashAndIndex`, `eth_getTransactionByBlockNumberAndIndex`
- `eth_getRawTransactionByBlockHashAndIndex`, `eth_getRawTransactionByBlockNumberAndIndex`
- `eth_sendRawTransactionSync`
- `eth_getLogs`

**State APIs:**
- `eth_call`, `eth_estimateGas`
- `eth_getBalance`, `eth_getTransactionCount`
- `eth_getCode`, `eth_getStorageAt`

**Subscription API:**
- `eth_subscribe("flashblocks", filter)` — address filtering, tx/receipt enrichment, header streaming

---

## State Root Computation

### Builder Side (`xlayer-builder`) — Three Modes

1. **Per-flashblock sync** (`disable_state_root = false`): Each flashblock calls `build_block(calculate_state_root=true)`. Inline: `state.merge_transitions()` → `hashed_post_state()` → `state_root_with_updates()`. Transition state is saved/restored for incremental builds.

2. **Disabled per-flashblock** (`disable_state_root = true`): Flashblocks emit `state_root = B256::ZERO`. Only the fallback payload (index 0) computes state root.

3. **Async on resolution** (`disable_async_calculate_state_root = false`): On `getPayload`, if best payload has zero state root, `resolve_zero_state_root` spawns on a blocking thread. Returns fallback payload immediately; async result pre-warms engine tree via `Events::BuiltPayload`.

### RPC Node Validator Side (`xlayer-flashblocks`) — Three Strategies

| Strategy | `PayloadProcessor` method | SR computation | Execution mode |
|---|---|---|---|
| `StateRootTask` | `spawn()` | Multiproof + sparse trie concurrent with execution | Full re-execution (all txs, not incremental) |
| `Parallel` | `spawn_cache_exclusive()` | Post-execution `ParallelStateRoot::incremental_root_with_updates()` | Incremental suffix execution |
| `Synchronous` | `spawn_cache_exclusive()` | Post-execution `StateRoot::root_with_updates()` via `database_provider_ro()` | Incremental suffix execution |

**Shared inputs**: All strategies use the same `OverlayStateProviderFactory` (anchored at `anchor_hash` from single `get_overlay_data()` snapshot) and `hashed_state = provider.hashed_post_state(&output.state)`. If both task and parallel fail, `compute_state_root_serial()` is the final synchronous fallback.

**Sparse trie atomicity via the shared mutex:** The `XLayerEngineValidator` mutex serializes all payload validation. The `PreservedSparseTrie` state transitions linearly: block N's computed trie → block N+1's starting anchor.
