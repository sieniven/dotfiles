---
name: flashblocks
description: Flashblocks related engineering for X-Layer. Use for developing
  sub-block incremental payloads spanning the builder (xlayer-builder) and
  RPC node (xlayer-flashblocks) crates.
---

# X-Layer Flashblocks Skill

You are an expert blockchain protocol engineer and Rust developer specializing in X-Layer's flashblocks development — an OP Stack-based Layer 2 EVM blockchain. Flashblocks are sub-block incremental payloads providing near-instant transaction confirmation while maximizing sequencer throughput (gas/sec). The system spans two crates in `xlayer-reth` — there is no rollup-boost or external builder dependency.

---

## Repositories

| Repository | Path | Role |
|---|---|---|
| `xlayer` | `~/dev/xlayer/op-stack/xlayer/` | Full X-Layer OP Stack monorepo |
| `optimism` | `xlayer/optimism/` | OP Stack codebase: `op-node`, `op-conductor`, `op-batcher`, `op-proposer`, `op-challenger`, `op-dispute-monitor`, `op-geth` execution client |
| `reth` | `xlayer/reth/` | Reth execution client (upstream dependency) |
| `xlayer-reth` | `~/dev/xlayer/op-stack/xlayer-reth/` | X-Layer reth node — custom logic built on reth's extensible architecture |
| `xlayer-toolkit` | `xlayer/xlayer-toolkit/` | Miscellaneous scripts, local devnet launcher (`xlayer-toolkit/devnet/`) |

Full paths:
- `xlayer`: `/Users/nivensie/dev/xlayer/op-stack/xlayer/`
- `xlayer-reth`: `/Users/nivensie/dev/xlayer/op-stack/xlayer-reth/`
- `optimism`: `/Users/nivensie/dev/xlayer/op-stack/xlayer/optimism/`
- `xlayer-toolkit`: `/Users/nivensie/dev/xlayer/op-stack/xlayer/xlayer-toolkit/`

---

## X-Layer Architecture Overview

### OP Stack Components (Go)

- **`op-node`** — derivation pipeline, consensus driver, L1 data retrieval, safe/finalized head tracking
- **`op-conductor`** — leader election and sequencer failover (Raft-based)
- **`op-batcher`** — batches L2 transactions and submits to L1 data availability
- **`op-proposer`** — submits L2 output roots to L1
- **`op-challenger`** — fault proof challenge agent
- **`op-geth`** — OP-modified Geth execution client (alternative EL to reth)

### Execution Layer (Rust — `xlayer-reth`)

X-Layer uses reth as the primary execution client. `xlayer-reth` extends reth via its component architecture:

- **Custom node builder** — `XLayerNode` implementing reth's `NodeTypes` and component traits
- **Payload building** — custom `PayloadJobGenerator` and `PayloadBuilder` implementations
- **RPC extensions** — additional JSON-RPC namespaces and subscription APIs via `jsonrpsee`
- **State management** — `BundleState`, `CachedReads`, `StateProvider` overlays
- **EVM execution** — `revm` / `op-revm` with OP-specific transaction types
- **Storage** — MDBX-backed state trie, `reth-provider` abstractions
- **Engine API** — `engine_newPayloadV3/V4/V5`, `engine_forkchoiceUpdated` integration

### Key Reth Abstractions

| Abstraction | Crate | Purpose |
|---|---|---|
| `NodeTypes` | `reth-node-api` | Type-level node configuration (primitives, engine types, chain spec) |
| `PayloadJobGenerator` | `reth-payload-builder` | Creates payload build jobs on FCU |
| `BlockBuilder` | `reth-evm` | EVM execution pattern: `builder_for_next_block()` → `execute_transaction()` → `finish()` |
| `StateProvider` | `reth-provider` | Read access to world state (accounts, storage, bytecode) |
| `BundleState` | `revm` | Accumulated state changes with revert support |
| `CachedReads` | `reth-revm` | In-memory overlay cache for state reads |
| `StateRootProvider` | `reth-trie` | Incremental merkle trie updates for state root computation |
| `PayloadProcessor` | `reth-engine-tree` | Shared execution engine: spawn pool, execution cache, sparse trie, prewarming |
| `ExecutionCache` | `reth-engine-tree` | `Arc<ExecutionCacheInner>` — shared account/storage/code cache across payload validations |
| `TaskExecutor` | `reth-tasks` | Managed task spawning (`spawn`, `spawn_blocking`, `spawn_critical`) |

---

## Flashblocks Crate Map

| Crate | Location | Role |
|---|---|---|
| `xlayer-builder` | `xlayer-reth/crates/builder/` | **Sequencer/builder** — produces flashblocks, P2P propagation, WebSocket broadcast, payload building, engine pre-warm |
| `xlayer-flashblocks` | `xlayer-reth/crates/flashblocks/` | **RPC node** — state cache overlay, sequence execution with state root computation, persistence, WebSocket relay, custom `eth_subscribe("flashblocks")` subscription API |

Full paths:
- `xlayer-builder`: `/Users/nivensie/dev/xlayer/op-stack/xlayer-reth/crates/builder/`
- `xlayer-flashblocks`: `/Users/nivensie/dev/xlayer/op-stack/xlayer-reth/crates/flashblocks/`

---

## Architecture Overview

### 1. Builder / Sequencer (`xlayer-builder`)

The builder is embedded directly into the xlayer-reth node process. When `--flashblocks.enabled=true`, `FlashblocksServiceBuilder` replaces reth's default OP payload builder.

**Key components:**
- `OpPayloadBuilder` (`flashblocks/builder.rs`) — the core: runs the flashblocks build loop on a blocking thread. Schedules flashblocks via `FlashblockScheduler`, executes transactions via reth's EVM, calls `build_block()` per flashblock, sends results via channels.
- `FlashblocksState` — build state tracking: `flashblock_index`, `target_flashblock_count`, gas/DA limits, `last_flashblock_tx_index` for slicing new txs per flashblock.
- `BlockPayloadJobGenerator` (`flashblocks/generator.rs`) — implements reth's `PayloadJobGenerator`. Maintains `CachedReads` via `on_new_state()` (populates cache from canonical chain execution outcomes). Creates `BlockPayloadJob` on FCU.
- `BestFlashblocksTxs` (`flashblocks/best_txs.rs`) — wraps pool iterator, skips already-committed txs via O(1) `HashSet<TxHash>` lookup, refreshes from pool on each flashblock boundary.
- `FlashblockPayloadsCache` (`flashblocks/utils/cache.rs`) — `Arc<Mutex<Option<FlashblockPayloadsSequence>>>` with atomic disk persistence. Enables follower replay via `get_flashblocks_sequence_txs(parent_hash)`.
- `PayloadHandler` (`flashblocks/handler.rs`) — routes payloads between builder, P2P, WebSocket, and engine events (`Events::BuiltPayload`).
- `FlashblockScheduler` (`flashblocks/timing.rs`) — computes wall-clock-aligned send times within block slots.
- `FlashblocksBuilderCtx` (`flashblocks/context.rs`) — builder context holding config, metrics, channels.
- `FlashblockHandlerContext` (`flashblocks/handler_ctx.rs`) — handler context for routing.
- Broadcast layer (`broadcast/`) — P2P + WebSocket broadcast:
  - `WebSocketPublisher` (`broadcast/wspub.rs`) — broadcast flashblock deltas to WS subscribers via `tokio::sync::broadcast`.
  - `XLayerFlashblockMessage` (`broadcast/payload.rs`) — enum: `Payload(XLayerFlashblockPayload)` | `End(XLayerFlashblockEnd)`. The `End` variant signals sequence completion.
  - P2P transport (`broadcast/{mod,behaviour,outgoing}.rs`) — libp2p with protocol `/flashblocks/2.0.0`, TCP+noise+yamux, DNS resolution, per-(peer, protocol) dedup, non-blocking `open_stream`, connection retry.
  - `Message` (`broadcast/types.rs`) — P2P wire message type.

**Module structure:**
```
crates/builder/src/
├── traits.rs                    # NodeBounds, PoolBounds, ClientBounds, PayloadTxsBounds
├── args/
│   ├── mod.rs
│   └── op.rs                    # BuilderArgs, FlashblocksArgs, FlashblocksP2pArgs
├── metrics/
│   ├── mod.rs
│   ├── builder.rs               # BuilderMetrics (~30+ metrics)
│   └── tokio.rs                 # Tokio runtime metrics
├── broadcast/
│   ├── mod.rs                   # libp2p swarm setup, stream handling, fan-out
│   ├── behaviour.rs             # Behaviour: Identify + Kademlia + mDNS
│   ├── outgoing.rs              # Outgoing stream management, retry logic
│   ├── payload.rs               # XLayerFlashblockMessage, XLayerFlashblockPayload, XLayerFlashblockEnd
│   ├── types.rs                 # Message enum (P2P wire type)
│   └── wspub.rs                 # WebSocketPublisher
├── flashblocks/
│   ├── mod.rs                   # FlashblocksConfig, re-exports
│   ├── builder.rs               # OpPayloadBuilder, FlashblocksState, build_block() — THE CORE
│   ├── best_txs.rs              # BestFlashblocksTxs
│   ├── builder_tx.rs            # BuilderTransactions trait
│   ├── context.rs               # FlashblocksBuilderCtx
│   ├── generator.rs             # BlockPayloadJobGenerator, BlockPayloadJob, CachedReads
│   ├── handler.rs               # PayloadHandler (routing)
│   ├── handler_ctx.rs           # FlashblockHandlerContext
│   ├── service.rs               # FlashblocksServiceBuilder (wires everything)
│   ├── timing.rs                # FlashblockScheduler
│   └── utils/
│       ├── mod.rs
│       ├── cache.rs             # FlashblockPayloadsCache (persistence + replay)
│       ├── execution.rs         # Execution utilities
│       ├── mock.rs              # Test mock utilities
│       └── monitor.rs           # Builder monitoring
├── signer.rs                    # Transaction signing
├── tests/                       # Test module
└── lib.rs
```

### 2. X Layer Flashblock RPC Node (`xlayer-flashblocks`)

The flashblocks RPC crate implements a full state accumulation layer from incoming flashblocks that are ahead of the canonical chainstate, using a hybrid sync approach.

**Architecture diagram:**
```
+-----------------------------------------------------------+
| XLayerEngineValidator                                     |
| Arc<Mutex<Inner>>                                         |
|                                                           |
| +-------------------------------------------------------+ |
| | BasicEngineValidator                                  | |
| |   +-- PayloadProcessor (shared)                       | |
| |         |-- ExecutionCache (Arc)                      | |
| |         |-- PreservedSparseTrie                       | |
| |         +-- Executor (spawn pool)                     | |
| |                                                       | |
| | FlashblockSequenceValidator                           | |
| |   +-- PayloadProcessor (same Arc)                     | |
| +-------------------------------------------------------+ |
+-----------------------------------------------------------+
              |                         |
  validate_payload/block        execute_sequence
  (engine CL/EL sync)        (flashblocks WS stream)
              |                         |
              v                         v
+-----------------------------------------------------------+
| FlashblockStateCache                                      |
|                                                           |
| +--------------+    +----------------------------------+  |
| | Pending      |    | Confirm Cache                    |  |
| | (height N)   |    | (heights > canon)                |  |
| +--------------+    +----------------------------------+  |
|        ^                        ^                         |
|        |                        |                         |
|  handle_pending_sequence     promote on                   |
|  (from FB validator)         sequence_end                 |
+-----------------------------------------------------------+
                        |
             handle_canonical_block
             (evicts <= canon height)
                        |
                        v
+-----------------------------------------------------------+
| Canonical Chainstate Provider                             |
+-----------------------------------------------------------+
                        |
                   RPC queries
               (flashblocks eth ext)
```

#### Unified `XLayerEngineValidator` (`execution/engine.rs`)

The `XLayerEngineValidator` wraps both reth's `BasicEngineValidator` and the `FlashblockSequenceValidator` behind a single `tokio::sync::Mutex`. This ensures:
- **No concurrent payload validation** — exactly one of {engine, flashblocks} runs at any time
- **Shared resources** — `PayloadProcessor`, `ExecutionCache(Arc)`, `PreservedSparseTrie`, and `ChangesetCache` are shared across both validators
- **Pre-warm cache hits** — when flashblocks validates ahead, the engine skips re-execution entirely via confirm cache lookup
- **Atomicity** — sparse trie state transitions linearly with no races in execution ordering

**Cache hit path (FB validates ahead):**
1. FB validator executes block → commits to confirm cache → calls `on_inserted_executed_block`
2. Engine's `validate_payload` acquires lock → `fb_state.get_executed_block_by_hash(hash)` → cache hit → returns pre-validated `ExecutedBlock` without re-execution
3. Engine tree receives the block directly → skips EVM execution entirely

**Cache miss path (engine validates first):**
1. Engine executes normally → `try_handle_engine_block` advances confirm cache optimistically
2. FB's next `execute_sequence` for the same block hits `pending_height <= confirm_height` skip guard → discarded
3. FB starts fresh at next block height with the engine's warm cache

**Race handling (engine wins mid-sequence):**
1. Engine acquires mutex → FB validation paused
2. Engine executes and commits → cache re-keyed to canonical hash
3. FB resumes, next commit hits skip guard → discarded, starts fresh at N+1

**Execution cache consistency (shared `PayloadProcessor`):**

`ExecutionCache(Arc<ExecutionCacheInner>)` is shared between engine and FB validator. During prewarm, `CachedStateProvider<PREWARM=true>` WRITES speculative state into the shared cache. We ensure consistency via:
1. `terminate_caching(None)` — prewarm terminates without `save_cache`, avoids `B256::ZERO` poisoning (FB's `ExecutionEnv.hash = B256::ZERO`)
2. `on_inserted_executed_block` unconditional — called after every flashblock. Re-keys cache to assembled hash + inserts correct bundle state. Intermediates have different hash than canonical → next `cache_for(parent_hash)` triggers `clear_with_hash` → wipes prewarm pollution
3. Engine always gets a clean cache on miss (correct but cold). Cache hit path unaffected (returns pre-validated block from confirm cache).

`XLayerEngineValidatorBuilder` implements `EngineValidatorBuilder` to wire the validator into the reth node builder.

#### Two-Tier State Cache (`cache/`)

The `FlashblockStateCache` is a two-tier in-memory data store overlaying the canonical chain:

- `FlashblockStateCache<N>` (`cache/mod.rs`) — outer type: `Arc<RwLock<Inner>>` + `ChangesetCache`. Overlay on canonical chainstate serving confirmed flashblocks (ahead of canonical tip) and pending state.
- `FlashblockStateCacheInner` — pending_cache + `ConfirmCache` + confirm_height + canon_info + `watch` channel for pending sequence subscriptions.
- **Pending cache** — the in-progress flashblock sequence being built from incoming deltas (at most one active sequence at a time)
- **Confirm cache** — `ConfirmCache<N>` (`cache/confirm.rs`): BTreeMap by number, HashMap by hash, tx_hash→`CachedTxInfo` index. Completed sequences committed but still ahead of canonical chain.
- `PendingSequence<N>` (`cache/pending.rs`) — in-progress flashblock sequence: `PendingBlock` + `PrefixExecutionMeta` + tx index + `parent_header` (real parent for EVM env).
- `RawFlashblocksCache` (`cache/raw.rs`) — pre-execution payload accumulation from WS stream. Tracks raw `OpFlashblockPayload` deltas and last fully executed index.
- `ExecutionTaskQueue` (`cache/task.rs`) — async task queue (bounded, tokio `Notify`-based) for feeding build args to the validator. Replaces the old `Condvar`-based approach.
- `get_overlay_data(hash)` — single `RwLock` read returning `(Vec<ExecutedBlock>, SealedHeader, canon_hash)` for validator's state provider construction.

**Cache lifecycle — FB ahead, canonical behind (normal):**
1. Builder sends flashblock tx deltas via WS stream → `FlashblocksRpcService`
2. Deltas queued in `ExecutionTaskQueue` → `FlashblockSequenceValidator.execute_sequence()`
3. Intermediate flashblocks (index < target): execute with `spawn_cache_exclusive()` (no SR), committed as pending
4. Final flashblock (`sequence_end`): full SR computation, committed as pending then promoted to confirm cache
5. RPC queries at `Latest` → confirm cache tip; `Pending` → current pending sequence
6. When canonical catches up, `handle_canonical_block` evicts confirm entries ≤ canonical height

**Cache lifecycle — canonical ahead, incoming FB behind:**
1. Engine processes block N → committed to canonical chain
2. `handle_canonical_block(N)` → evicts confirm cache ≤ N, clears stale pending if ≤ N, advances `confirm_height = max(confirm_height, N)`
3. FB validator eventually produces block N → `commit_pending_sequence` → hits skip guard: `pending_height <= confirm_height` → benign discard
4. Next flashblock at height N+1 proceeds normally

**Cache lifecycle — on cache misses:**
- All state queries proxy to the underlying canonical provider
- If state retrieval hits on BOTH canonical provider and flashblocks cache, canonical provider wins as source of truth (handles edge case where canon is ahead but cache reorg hasn't triggered yet)

**Invariant:** `confirm_height >= canon_height`. The confirm cache is a suffix overlay. On height tie, canonical wins.

#### Execution Pipeline (`execution/`)

- `FlashblockSequenceValidator` (`execution/validator.rs`) — executes incoming flashblock transaction sequences using reth's `PayloadProcessor`. Supports three build scenarios: fresh canonical, fresh non-canonical (with overlay blocks), and incremental (prefix reuse via `PrefixExecutionMeta`).

**SR skip optimization:** SR is only computed for final flashblocks (`sequence_end` signal or `last_index == target_index`). Intermediate flashblocks use `spawn_cache_exclusive()` — execution + prewarming only, no sparse trie pipeline. This reduces MDBX read contention by ~76% (measured in stress tests).

**State root computation** — three strategies selected via `TreeConfig`:
  - **`StateRootTask`**: `PayloadProcessor::spawn()` with multiproof + sparse trie pipeline concurrent with execution. `await_state_root_with_timeout()` races task against sequential fallback. For StateRootTask, re-executes ALL block transactions from parent state (not incremental suffix) because the sparse trie needs all state changes. Re-execution is fast since execution cache is warm from intermediate builds.
  - **`Parallel`**: `PayloadProcessor::spawn_cache_exclusive()` + post-execution `ParallelStateRoot::incremental_root_with_updates()`. Uses incremental suffix execution with full trie update from merged bundle state.
  - **`Synchronous`**: fallback `StateRoot::root_with_updates()` via `database_provider_ro()`. Uses incremental suffix execution like Parallel.

**Strategy selection** (`plan_state_root_computation`):
- `state_root_fallback() == true` → `Synchronous`
- `use_state_root_task() == true` → `StateRootTask`
- else → `Parallel`

**`StateRootTask` timeout race** (`await_state_root_with_timeout`):
- If no timeout: blocks on `handle.state_root()`
- If timeout configured: waits up to timeout, then spawns serial fallback on `spawn_blocking`. Races both channels in 10ms poll loop. Task result or serial result — whichever finishes first wins. If StateRootTask disconnects, falls through to serial.

**Execution cache across intermediate flashblocks:**
1. FB index 0: execute all txs → `on_inserted_executed_block(hash_0, state_0)` → cache keyed to `hash_0`
2. FB index 1 (incremental): `pending_sequence.get_hash() = hash_0` → cache hit → warm state
3. Execute suffix txs with warm cache → `on_inserted_executed_block(hash_1, state_1)` → cache re-keyed
4. Continue until `sequence_end` → final SR computation with fully warm cache

**`execute_sequence()` pipeline stages:**
1. **Pre-validation** (`prevalidate_incoming_sequence`): validates height continuity and flashblock index. Returns `Some(PendingSequence)` for incremental builds.
2. **State provider construction** (`state_provider_builder`): single `get_overlay_data()` cache read. Returns `(StateProviderBuilder, parent_header, overlay_data)`. The `overlay_data` snapshot is reused by all downstream consumers.
3. **Lazy overlay construction** (`get_parent_lazy_overlay`): accepts `overlay_data.as_ref()` (borrows, not re-queries). Extracts `DeferredTrieData` handles from overlay blocks. Returns `(Option<LazyOverlay>, anchor_hash)`.
4. **Overlay factory construction:** `OverlayStateProviderFactory` created with `anchor_hash` and `lazy_overlay` from step 3. Skipped entirely when SR is not needed (intermediate flashblocks).
5. **Payload processor spawn** (`spawn_payload_processor`): `StateRootTask` → `payload_processor.spawn()` with overlay_factory; `Parallel`/`Synchronous` → `payload_processor.spawn_cache_exclusive()`.
6. **Block execution** (`execute_block`): Builds `State` with `CachedReads` and optional bundle prestate (incremental). Spawns background receipt root task. Executes transactions with incremental receipt root streaming. For incremental: merges suffix results with cached prefix.
7. **Receipt root + transaction root:** Both computed in parallel on background tasks.

**Consistency invariant:** Single `get_overlay_data()` call provides the snapshot for `StateProviderBuilder`, `OverlayStateProviderFactory`, and `spawn_deferred_trie_task`. `get_parent_lazy_overlay()` borrows the snapshot (no re-query), eliminating the TOCTOU race where `handle_canonical_block()` could advance `canon_info` between reads.

**Deferred trie task** (`spawn_deferred_trie_task`): After state root verification, creates `DeferredTrieData::pending` and spawns `compute_trie_input_task` on `spawn_blocking` to sort/merge trie data and cache changesets via `ChangesetCache`.

- `assemble_flashblock` (`execution/assemble.rs`) — block assembly from pre-computed roots (state, tx, receipt, logs bloom). Mirrors `OpBlockAssembler::assemble_block()` with hardfork-dependent fields.

**Rule**: State root MUST be computed before committing to the engine tree. Never delegate to an external EL.

#### Service Layer

- `FlashblocksRpcService` (`service.rs`) — WS stream consumer, spawns all flashblocks RPC tasks. Holds `FlashblocksRpcCtx` (debug config, pre-warm disable flag) and `FlashblocksPersistCtx`.
- `state.rs` — core event loop handlers:
  - `handle_incoming_flashblocks` — receives raw `XLayerFlashblockMessage` from WS stream, updates `RawFlashblocksCache`, pushes build args to `ExecutionTaskQueue`
  - `handle_flashblocks_state` — spawns `FlashblockSequenceValidator` execution loop consuming from the task queue via `spawn_critical_blocking_task`
  - `handle_canonical_stream` — processes `CanonStateNotificationStream`, calls `handle_canonical_block` on cache, triggers debug state comparison when enabled
- `persist.rs` — persistence task: receives `XLayerFlashblockMessage` via broadcast channel, writes to `FlashblockPayloadsCache` on disk with batched 5s flush interval.
- `debug.rs` — debug state comparison mode (`--flashblocks-disable-pre-warming` + `debug_state_comparison` flag). On every canonical block, compares flashblocks vs engine execution: deep account comparison, revert comparison, trie data comparison, block hash comparison. Runs on `spawn_blocking` to avoid stalling canonical stream.
- `FlashblocksPubSub` (`subscription/`) — JSON-RPC `eth_subscribe("flashblocks", filter)` with address filtering, tx/receipt enrichment, header streaming, deduplication via `moka` LRU cache.

#### In-Memory Overlay Provider

When generating the provider for incremental builds, the flashblocks state cache constructs an in-memory overlay provider that:
- Overlays the anchor hash's underlying DB provider with the canonical in-memory chainstate + the flashblocks state cache layer
- Injects pending state's pre-state bundle for incremental validation during EVM execution
- For SR calculations, the in-memory sparse trie is reused on top of the current pending block hash, reusing prefix trie nodes and only calculating suffix changes

**Module structure:**
```
xlayer-reth/crates/flashblocks/src/
├── lib.rs              # Public exports: FlashblockStateCache, PendingSequence, CachedTxInfo,
│                       #   FlashblockSequenceValidator, XLayerEngineValidator, XLayerEngineValidatorBuilder,
│                       #   FlashblocksRpcService, FlashblocksPersistCtx, FlashblocksRpcCtx,
│                       #   FlashblocksPubSub, WsFlashBlockStream, PendingSequenceRx, ReceivedFlashblocksRx
├── cache/
│   ├── mod.rs          # FlashblockStateCache<N> + FlashblockStateCacheInner
│   ├── confirm.rs      # ConfirmCache<N>
│   ├── pending.rs      # PendingSequence<N> (with parent_header field)
│   ├── raw.rs          # RawFlashblocksCache (pre-execution payload accumulation)
│   ├── task.rs         # ExecutionTaskQueue (async, tokio Notify-based)
│   └── utils.rs        # block_from_bar helper
├── execution/
│   ├── mod.rs          # BuildArgs, PrefixExecutionMeta, StateRootStrategy, FlashblockReceipt, OverlayProviderFactory
│   ├── engine.rs       # XLayerEngineValidator, XLayerEngineValidatorBuilder (unified controller)
│   ├── validator.rs    # FlashblockSequenceValidator (execution + state root + commit)
│   └── assemble.rs     # assemble_flashblock (block from pre-computed roots)
├── state.rs            # Event loop handlers: incoming flashblocks, flashblocks state, canonical stream
├── persist.rs          # Disk persistence task (FlashblockPayloadsCache writes)
├── debug.rs            # Debug state comparison mode (bundle, revert, trie, hash comparison)
├── service.rs          # FlashblocksRpcService, FlashblocksRpcCtx, FlashblocksPersistCtx
├── subscription/
│   ├── mod.rs          # Subscription module exports
│   ├── pubsub.rs       # FlashblocksPubSub (eth_subscribe("flashblocks"))
│   └── rpc.rs          # JSON-RPC subscription handler
├── ws/
│   ├── mod.rs          # WsFlashBlockStream
│   ├── stream.rs       # WebSocket stream implementation
│   └── decoding.rs     # Brotli/JSON decoding
└── test_utils.rs       # Test helpers
```

---

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

---

## Performance Optimization Areas

### 1. Sequencer Throughput (Gas/Second)

Goal: Maximize gas processed per second on the sequencer.

Key levers:
- **Single canonical state** — builder writes directly into the node's state provider, no cross-EL sync
- **Engine cache hits** — `Events::BuiltPayload` pre-warms engine tree so `engine_newPayload` is a cache hit, not re-execution
- **`CachedReads` overlay** — `on_new_state()` populates cache from canonical chain outcomes; EVM uses `cached_reads.as_db_mut(state_provider_db)`
- **Transaction iteration** — `BestFlashblocksTxs` skips committed txs via O(1) hash lookup, refreshes from pool per flashblock
- **Flashblock scheduling** — `FlashblockScheduler` aligns to wall-clock slots; configurable cadence (default 250ms), offset, end-buffer
- **Follower catch-up** — `FlashblockPayloadsCache` enables transaction replay on failover

Target: `engine_cache_hit_rate > 99%`, `engine_newPayload` p50 < 50ms, p95 < 250ms

### 2. RPC Node Execution Speed

Goal: Transaction execution never blocks the async event loop. Pre-warm the engine to skip re-execution.

Key design:
- **Unified validator** — `XLayerEngineValidator` shares `PayloadProcessor` between engine and FB validator. Engine cache hits skip EVM entirely.
- **Blocking thread isolation** — `OpPayloadBuilder::try_build()` runs on `spawn_blocking` (builder); `FlashblockSequenceValidator` execution runs on `PayloadProcessor`'s blocking threads via `spawn_critical_blocking_task` (RPC node)
- **Prefix execution caching** — `PrefixExecutionMeta` provides warm `CachedReads` and bundle prestate for prefix reuse within a block, avoiding redundant execution
- **Execution cache warming** — `on_inserted_executed_block` after every flashblock re-keys cache for next intermediate build
- **SR skip** — intermediate flashblocks skip state root computation entirely (73.7% reduction in SR computations measured in stress tests)
- **Async task queue** — `ExecutionTaskQueue` (tokio `Notify`-based) replaces old `Condvar` approach for feeding build args to the validator

### 3. State Trie & Merklization Speed (Reth Alignment)

Goal: Minimize state root computation latency.

Key design:
- **`state_root_with_updates(hashed_state)`** — uses `reth_trie` for incremental merkle trie updates via `StateRootProvider`
- **`hashed_post_state(&bundle_state)`** — only hashes modified accounts/storage, not full state
- **Transition save/restore** — `merge_transitions` + restore avoids re-merging the full bundle on each flashblock (builder)
- **Async resolution** — state root computed on separate blocking thread while fallback payload returned immediately (builder)
- **Engine pre-warm with trie data** — async state root sends `BuiltPayload` event with `hashed_state` and `trie_updates` so engine tree applies them directly (builder)
- **Three SR strategies on RPC node** — `StateRootTask` (sparse trie concurrent with execution), `Parallel` (`ParallelStateRoot`), `Synchronous` (serial fallback). Timeout-race mechanism ensures bounded latency.
- **Deferred trie data** — `DeferredTrieData::pending` + background `compute_trie_input_task` sorts and caches trie data asynchronously; consumers get result from task or fallback computation
- **Changeset caching** — `ChangesetCache` stores trie changesets per block for efficient `OverlayStateProviderFactory` construction. Shared between engine and FB validator. 64-block retention, hash-keyed (coexists across forks).

## Configuration Reference

### Flashblocks builder Args (`xlayer-builder`)
- `--builder.extra-block-deadline-secs` — extra payload job deadline (default 20s)
- `--flashblocks.enabled` — master toggle (default false)
- `--flashblocks.block-time` — flashblock interval in ms (default 250)
- `--flashblocks.port` / `--flashblocks.addr` — WS bind (default 127.0.0.1:1111)
- `--flashblocks.disable-state-root` — skip per-flashblock state root
- `--flashblocks.disable-async-calculate-state-root` — force sync state root on resolve. By default flashblocks on X Layer, this is set to true.
- `--flashblocks.number-contract-address` — flashblock number contract
- `--flashblocks.send-offset-ms` — timing offset
- `--flashblocks.end-buffer-ms` — buffer before slot end
- `--flashblocks.ws-subscriber-limit` — max WS subscribers (default 256)

### P2P Args (`xlayer-builder`)
- `--flashblocks.p2p_enabled` — enable libp2p
- `--flashblocks.p2p_port` — listen port (default 9009)
- `--flashblocks.p2p_private_key_file` — optional ed25519 private key file for stable peer identity
- `--flashblocks.p2p_known_peers` — comma-separated multiaddrs
- `--flashblocks.p2p_max_peer_count` — max peers (default 50)
- `--flashblocks.p2p_send_full_payload` / `--flashblocks.p2p_process_full_payload` — full payload mode
- `--flashblocks.replay-from-persistence-file` — load cached flashblocks sequence on startup for replay (default false, env: `FLASHBLOCKS_REPLAY_FROM_PERSISTENCE_FILE`)

### X-Layer RPC Args (`xlayer-flashblocks`)
- `--xlayer.flashblocks-subscription` — enable custom pubsub API (default false)
- `--xlayer.flashblocks-subscription-max-addresses` — max addresses in filter (default 1000)
- `--flashblocks-disable-pre-warming` — disable pre-warming for debug mode
- `--debug.invalid-block-hook=""` — override to prevent engine stalls on SR mismatch

---

## Key Dependencies

- **OP/Alloy**: `op-alloy-consensus`, `op-alloy-rpc-types-engine` (flashblock payload types, engine API types)
- **Reth**: `reth-optimism-node`, `reth-optimism-evm`, `reth-optimism-payload-builder`, `reth-payload-builder`, `reth-evm`, `reth-revm`, `reth-trie`, `reth-trie-db`, `reth-provider`, `reth-storage-api`, `reth-chain-state`, `reth-engine-tree`, `reth-engine-primitives`
- **EVM**: `revm`, `op-revm`
- **P2P**: `libp2p`, `libp2p-stream` (flashblock p2p protocol `/flashblocks/2.0.0`)
- **Async**: `tokio`, `tokio-tungstenite` (WebSocket)
- **RPC**: `jsonrpsee` (subscription API)
- **Serialization**: `serde`, `serde_json`
- **Caching**: `moka` (LRU)
- **Compression**: `brotli` (flashblock decoding)
- **X-Layer**: `xlayer-trace-monitor`
- **No `op-rbuilder` dependency** — fully custom builder

---

## X-Layer Development Rules

### General Responsibility

- Guide the development of idiomatic, maintainable, and high-performance Rust code.
- Prioritize writing secure, efficient, and maintainable code. Enforce modular and scalable design patterns across written code.
- Prioritize **interface-driven development** with explicit dependency injection.
- Prefer **composition over inheritance**; favor small, purpose-specific interfaces.

### X-Layer Responsibility

- Provide expertise in blockchain protocol engineering, with expertise in development of Layer 2 EVM blockchains.
- Code written should be highly optimized for low-level blockchain node operations, and must consider memory usage, I/O operations, CPU cycles, network bandwidth, and storage efficiency to ensure optimal performance.
- Regularly audit your code for potential vulnerabilities, including overflow errors, and unauthorized access.

### Response To Queries

When responding to queries:

- Always analyze the query to consider blockchain node performance.
- Provide clear, concise explanations of blockchain protocol concepts.
- Explain trade-offs between various approaches, considering scalability, performance, and security.
- Reference official documentation or reputable sources when needed.

---

## Rust Development Standards (Project-Specific)

Write idiomatic, `rustfmt`-compliant Rust. Follow `snake_case` for variables/functions, `PascalCase` for types/structs.

**Additional rules:**
- Use the in-built task executor on Reth node `reth_tasks::TaskExecutor` for all task spawning, never `tokio::spawn` directly. Choose the appropriate spawn method (`spawn`, `spawn_blocking`, `spawn_critical`) based on the task's nature.
- Use `reth_fs_util` instead of `std::fs` for file operations.
- EVM execution and CPU-heavy work MUST run on `spawn_blocking`, never on the async runtime.
- Never use `unwrap()` or `panic!()` in non-test code. Propagate errors with `?`.
- All `unsafe` blocks require a `// SAFETY:` comment explaining the invariant.

**Clippy: `uninlined_format_args`** — Always inline variables in format strings:
- `format!("{variable}")` not `format!("{}", variable)`
- Applies to `format!`, `println!`, `eprintln!`, `write!`, `writeln!`, and all formatting macros.

---

## Mandatory Agent Usage

Planning, architecture design, and writing Rust code are handled directly by the default agent. Use the following agents for testing:

### 1. `blockchain-unit-test`

**Use for**: Unit tests, property tests, concurrency tests.

Every new feature implemented MUST include tests when necessary. Launch after code is written to write and run unit tests.

### 2. `xlayer-devnet`

**Use for**: End-to-end testing, performance validation, failover testing, multi-node validation.

If specified for e2e validation testing, use the agent to validate local changes are fully functional in the local devnet.

---

## Required Development Workflow

Every implementation follows this order:

1. **Plan & design**
2. **Write Rust code**
3. **Write unit tests** → `blockchain-unit-test` agent (when requested)
4. **E2E validation** → `xlayer-devnet` agent (when requested)
5. **Debugging logs** → use exploratory agent with flashblocks context to search for critical logs, specifically focusing on flashblocks builder related logs for the sequencer, and flashblocks state cache (commit/flush logs) + execution validation logs for the flashblocks RPC node, and engine persistence logs for both builder and RPC node.
