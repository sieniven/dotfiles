# Flashblocks architecture

Builder/sequencer (`xlayer-builder`) and RPC node (`xlayer-flashblocks`) internals: engine validator, two-tier state cache, execution pipeline, service layer, overlay provider.

## Contents

- [Architecture Overview](#architecture-overview)
  - [1. Builder / Sequencer (`xlayer-builder`)](#1-builder--sequencer-xlayer-builder)
  - [2. X Layer Flashblock RPC Node (`xlayer-flashblocks`)](#2-x-layer-flashblock-rpc-node-xlayer-flashblocks)

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
