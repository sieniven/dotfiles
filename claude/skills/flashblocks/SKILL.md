---
name: flashblocks
description: Flashblocks related engineering for X-Layer. Use for developing
  sub-block incremental payloads spanning the builder (xlayer-builder), consumer
  (reth-optimism-flashblocks), and RPC node (xlayer-flashblocks) crates.
---

# X-Layer Flashblocks Skill

You are an expert blockchain protocol engineer and Rust developer specializing in X-Layer's flashblocks development — an OP Stack-based Layer 2 EVM blockchain. Flashblocks are sub-block incremental payloads providing near-instant transaction confirmation while maximizing sequencer throughput (gas/sec). The system spans three crates across two repositories — there is no rollup-boost or external builder dependency.

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
| `TaskExecutor` | `reth-tasks` | Managed task spawning (`spawn`, `spawn_blocking`, `spawn_critical`) |

---

## Flashblocks Crate Map

| Crate | Location | Role |
|---|---|---|
| `xlayer-builder` | `xlayer-reth/crates/builder/` | **Sequencer/builder** — produces flashblocks, P2P propagation, WebSocket broadcast, payload building, engine pre-warm |
| `reth-optimism-flashblocks` | `optimism/rust/op-reth/crates/flashblocks/` | **Flashblock RPC** — receives flashblocks via WS, EVM execution, builds pending state, consensus integration for RPC nodes (`engine_newPayload` + FCU), sequence management, transaction caching |
| `xlayer-flashblocks` | `xlayer-reth/crates/flashblocks/` | **Flashblock RPC node supporting custom X Layer subscription** — disk persistence, WebSocket relay, custom `eth_subscribe("flashblocks")` subscription API with address filtering |

Full paths:
- `xlayer-builder`: `/Users/nivensie/dev/xlayer/op-stack/xlayer-reth/crates/builder/`
- `reth-optimism-flashblocks`: `/Users/nivensie/dev/xlayer/op-stack/xlayer/optimism/rust/op-reth/crates/flashblocks/`
- `xlayer-flashblocks`: `/Users/nivensie/dev/xlayer/op-stack/xlayer-reth/crates/flashblocks/`

---

## Architecture Overview

### 1. Builder / Sequencer (`xlayer-builder`)

The builder is embedded directly into the xlayer-reth node process. When `--flashblocks.enabled=true`, `FlashblocksServiceBuilder` replaces reth's default OP payload builder.

**Key components:**
- `OpPayloadBuilder` (`payload/flashblocks/payload.rs`) — the core: runs the flashblocks build loop on a blocking thread. Schedules flashblocks via `FlashblockScheduler`, executes transactions via reth's EVM, calls `build_block()` per flashblock, sends results via channels.
- `FlashblocksState` — build state tracking: `flashblock_index`, `target_flashblock_count`, gas/DA limits, `last_flashblock_tx_index` for slicing new txs per flashblock.
- `BlockPayloadJobGenerator` (`payload/generator.rs`) — implements reth's `PayloadJobGenerator`. Maintains `CachedReads` via `on_new_state()` (populates cache from canonical chain execution outcomes). Creates `BlockPayloadJob` on FCU.
- `BestFlashblocksTxs` (`best_txs.rs`) — wraps pool iterator, skips already-committed txs via O(1) `HashSet<TxHash>` lookup, refreshes from pool on each flashblock boundary.
- `FlashblockPayloadsCache` (`cache.rs`) — `Arc<Mutex<Option<FlashblockPayloadsSequence>>>` with atomic disk persistence. Enables follower replay via `get_flashblocks_sequence_txs(parent_hash)`.
- `PayloadHandler` (`handler.rs`) — routes payloads between builder, P2P, WebSocket, and engine events (`Events::BuiltPayload`).
- `FlashblockScheduler` (`timing.rs`) — computes wall-clock-aligned send times within block slots.
- `WebSocketPublisher` (`wspub.rs`) — broadcast flashblock deltas to WS subscribers via `tokio::sync::broadcast`.
- P2P layer (`p2p/`) — libp2p with protocol `/flashblocks/1.0.0`, TCP+noise+yamux, mDNS discovery, fan-out broadcast.

**Module structure:**
```
crates/builder/src/
├── traits.rs                 # NodeBounds, PoolBounds, ClientBounds, PayloadTxsBounds
├── args/op.rs                # BuilderArgs, FlashblocksArgs, FlashblocksP2pArgs
├── metrics/builder.rs        # BuilderMetrics (~30+ metrics)
├── p2p/{mod,behaviour,outgoing}.rs  # libp2p transport, behaviour, broadcast
├── payload/
│   ├── generator.rs          # BlockPayloadJobGenerator, BlockPayloadJob, CachedReads
│   ├── context.rs            # OpPayloadBuilderCtx (EVM config, DA config)
│   ├── builder_tx.rs         # BuilderTransactions trait
│   └── flashblocks/
│       ├── payload.rs        # OpPayloadBuilder, FlashblocksState, build_block() — THE CORE
│       ├── service.rs        # FlashblocksServiceBuilder (wires everything)
│       ├── handler.rs        # PayloadHandler (routing)
│       ├── cache.rs          # FlashblockPayloadsCache (persistence + replay)
│       ├── timing.rs         # FlashblockScheduler
│       ├── wspub.rs          # WebSocketPublisher
│       ├── best_txs.rs       # BestFlashblocksTxs
│       ├── p2p.rs            # Message enum, protocol definition
│       ├── config.rs         # FlashblocksConfig
│       └── context.rs        # FlashblockHandlerContext
└── tx/{signer,mock}.rs       # Signing, test utilities
```

### 2. Flashblock RPC nodes (`reth-optimism-flashblocks`)

The upstream reth crate that RPC/follower nodes use to consume flashblocks from a sequencer's WebSocket stream and build local pending state.

**Key components:**
- `FlashBlockService` (`service.rs`) — main event loop (`tokio::select!`): processes incoming flashblocks, manages build jobs, reconciles canonical blocks. Three events: incoming flashblock, build job complete, canonical block notification.
- `SequenceManager` (`cache.rs`) — ring buffer (3 slots) of recently completed sequences. Manages build ticket selection: canonical pending > cached sequence > speculative with pending parent.
- `FlashBlockBuilder` (`worker.rs`) — EVM execution on `spawn_blocking`. Uses reth's `BlockBuilder` pattern (`builder_for_next_block()` → `execute_transaction()` → `finish()`). For cached prefix builds, uses lower-level `create_executor()` to skip pre-execution changes.
- `TransactionCache` (`tx_cache.rs`) — caches cumulative `BundleState`, receipts, and execution metadata from previous flashblock builds within the same block. Uses prefix matching: only resumes when cached tx list is a prefix of incoming list.
- `PendingStateRegistry` (`pending_state.rs`) — bounded HashMap (64 entries) of `PendingBlockState`. Enables speculative building when flashblocks for block N+1 arrive before canonical block N. Each entry stores `canonical_anchor_hash` pointing back to the last canonical block.
- `FlashBlockConsensusClient` (`consensus.rs`) — submits `engine_newPayload` (when state_root is non-zero) and `engine_forkChoiceUpdated` using V5 API.
- `FlashblockSequenceValidator` (`validation.rs`) — classifies incoming flashblocks: `NextInSequence`, `FirstOfNextBlock`, `Duplicate`, `NonSequentialGap`, `InvalidNewBlockIndex`.
- `ReorgDetector` / `CanonicalBlockReconciler` (`validation.rs`) — detects reorgs via block fingerprints, determines reconciliation strategy: `CatchUp`, `HandleReorg`, `DepthLimitExceeded`, `Continue`.
- WebSocket layer (`ws/`) — `WsFlashBlockStream` connects to sequencer WS, decodes brotli/JSON via `FlashBlockDecoder`, auto-reconnects on failure.

**Channel outputs:**
- `PendingBlockRx<N>` (`watch`) — latest pending block for `eth_getBlock("pending")`
- `FlashBlockCompleteSequenceRx` (`broadcast`) — completed sequences for consensus submission
- `FlashBlockRx` (`broadcast`) — raw individual flashblocks for downstream subscription APIs
- `InProgressFlashBlockRx` (`watch`) — build-in-progress signaling

**Epoch-based invalidation:** `state_epoch` counter increments on reorg/catch-up, invalidating all in-flight build results.

**Module structure:**
```
optimism/rust/op-reth/crates/flashblocks/src/
├── lib.rs              # FlashblocksListeners, channel type aliases
├── service.rs          # FlashBlockService (main orchestrator)
├── cache.rs            # SequenceManager (ring buffer), BuildTicket, BuildCandidate
├── worker.rs           # FlashBlockBuilder (EVM execution)
├── tx_cache.rs         # TransactionCache (incremental prefix caching)
├── pending_state.rs    # PendingStateRegistry (speculative chaining)
├── validation.rs       # Sequence validation, reorg detection, reconciliation
├── consensus.rs        # FlashBlockConsensusClient (engine API)
├── payload.rs          # FlashBlock type alias, PendingFlashBlock
├── sequence.rs         # FlashBlockPendingSequence, FlashBlockCompleteSequence
├── ws/{mod,decoding,stream}.rs  # WebSocket stream, brotli/JSON decoding
└── test_utils.rs       # Test factories
```

### 3. X Layer Flashblock RPC Node Extensions (`xlayer-flashblocks`)

X-Layer custom logic for flashblock RPC nodes: persistence, WebSocket relay, and a custom flashblock subscription API.

**Key components:**
- `FlashblocksService` (`handler.rs`) — spawns two critical tasks: disk persistence (writes each flashblock to `FlashblockPayloadsCache` + atomic file persist) and WebSocket relay (forwards flashblocks to `WebSocketPublisher`).
- `FlashblocksPubSub` (`subscription.rs`) — JSON-RPC `eth_subscribe("flashblocks", filter)` with:
  - Address filtering (sender, recipient, log-emitting addresses)
  - Optional transaction enrichment (`tx_info: bool`)
  - Optional receipt enrichment (`tx_receipt: bool`)
  - Header streaming (`header_info: bool`)
  - Transaction deduplication via `moka` LRU cache (10,000 entries)
  - Configurable max subscribed addresses (default 1000)
- Data types (`pubsub.rs`) — `FlashblockSubscriptionKind`, `FlashblocksFilter`, `SubTxFilter`, `FlashblockStreamEvent` (tagged: `Header` | `Transaction`), `EnrichedTransaction`.

**Wiring** (in `main.rs`): When NOT in sequencer mode, `FlashblocksService` is created with the `FlashBlockRx` from the upstream service. If `--xlayer.flashblocks-subscription` is enabled, `FlashblocksPubSub` replaces the standard `eth` pubsub module.

**Module structure:**
```
xlayer-reth/crates/flashblocks/src/
├── lib.rs              # Re-exports
├── handler.rs          # FlashblocksService (persistence + WS relay)
├── pubsub.rs           # Subscription data types and filters
└── subscription.rs     # FlashblocksPubSub JSON-RPC API
```

---

## Flashblocks Payload Model

Uses types from `op-alloy-rpc-types-engine`:

- **`OpFlashblockPayload`** — wire format for each flashblock delta:
  - `payload_id: PayloadId`
  - `index: u64` — 0 = base/fallback, 1..N = incremental flashblocks
  - `base: Option<OpFlashblockPayloadBase>` — only at index 0: `parent_hash`, `fee_recipient`, `prev_randao`, `block_number`, `gas_limit`, `timestamp`, `extra_data`, `base_fee_per_gas`
  - `diff: OpFlashblockPayloadDelta` — `state_root`, `receipts_root`, `logs_bloom`, `gas_used`, `block_hash`, `transactions`, `withdrawals`, `withdrawals_root`, `blob_gas_used`
  - `metadata: OpFlashblockPayloadMetadata` — `receipts` (by tx hash), `new_account_balances`, `block_number`

---

## State Root Computation (Builder — Three Modes)

1. **Per-flashblock sync** (`disable_state_root = false`): Each flashblock calls `build_block(calculate_state_root=true)`. Inline: `state.merge_transitions()` → `hashed_post_state()` → `state_root_with_updates()`. Transition state is saved/restored for incremental builds.

2. **Disabled per-flashblock** (`disable_state_root = true`): Flashblocks emit `state_root = B256::ZERO`. Only the fallback payload (index 0) computes state root.

3. **Async on resolution** (`disable_async_calculate_state_root = false`): On `getPayload`, if best payload has zero state root, `resolve_zero_state_root` spawns on a blocking thread. Returns fallback payload immediately; async result pre-warms engine tree via `Events::BuiltPayload`.

**Consumer side**: `FlashBlockConsensusClient` submits `engine_newPayload` only when `state_root != B256::ZERO`. FCU is always sent.

**Rule**: State root MUST be computed before committing to the engine tree. Never delegate to an external EL.

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

### 2. Execution Speed (Reth Alignment)

Goal: Transaction execution never blocks the async event loop.

Key design:
- **Blocking thread isolation** — `OpPayloadBuilder::try_build()` runs on `spawn_blocking` (builder); `FlashBlockBuilder` uses `TaskExecutor::spawn_blocking()` (consumer)
- **Reth EVM path** — standard `evm.transact()` with `CachedReads` overlay (builder); `BlockBuilder` pattern with `execute_transaction()` (consumer)
- **Incremental state** — `BundleState` with `BundleRetention::Reverts` allows incremental flashblock builds; transition state snapshotted/restored between flashblocks (builder)
- **Transaction prefix caching** — `TransactionCache` provides warm `BundleState` prestate for prefix reuse within a block, avoiding redundant execution (consumer)
- **DA-aware execution** — per-tx DA size check (`OpDAConfig`) prevents DA overflow mid-flashblock

### 3. State Trie & Merklization Speed (Reth Alignment)

Goal: Minimize state root computation latency.

Key design:
- **`state_root_with_updates(hashed_state)`** — uses `reth_trie` for incremental merkle trie updates via `StateRootProvider`
- **`hashed_post_state(&bundle_state)`** — only hashes modified accounts/storage, not full state
- **Transition save/restore** — `merge_transitions` + restore avoids re-merging the full bundle on each flashblock
- **Async resolution** — state root computed on separate blocking thread while fallback payload returned immediately
- **Engine pre-warm with trie data** — async state root sends `BuiltPayload` event with `hashed_state` and `trie_updates` so engine tree applies them directly
- **Consumer-side auto state root** — triggered near expected final flashblock index (based on `block_time`)

---

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
- `--flashblocks.p2p_known_peers` — comma-separated multiaddrs
- `--flashblocks.p2p_max_peer_count` — max peers (default 50)
- `--flashblocks.p2p_send_full_payload` / `--flashblocks.p2p_process_full_payload` — full payload mode

### X-Layer RPC Args (`xlayer-flashblocks`)
- `--xlayer.flashblocks-subscription` — enable custom pubsub API (default false)
- `--xlayer.flashblocks-subscription-max-addresses` — max addresses in filter (default 1000)

---

## Key Dependencies

- **OP/Alloy**: `op-alloy-consensus`, `op-alloy-rpc-types-engine` (flashblock payload types, engine API types)
- **Reth**: `reth-optimism-node`, `reth-optimism-evm`, `reth-optimism-payload-builder`, `reth-payload-builder`, `reth-evm`, `reth-revm`, `reth-trie`, `reth-provider`, `reth-storage-api`, `reth-chain-state`
- **EVM**: `revm`, `op-revm`
- **P2P**: `libp2p`, `libp2p-stream` (flashblock p2p protocol)
- **Async**: `tokio`, `tokio-tungstenite` (WebSocket)
- **RPC**: `jsonrpsee` (subscription API)
- **Serialization**: `serde`, `serde_json`
- **Caching**: `moka` (LRU), `ringbuffer` (sequence ring buffer)
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

1. **Plan & design** → default agent
2. **Write Rust code** → default agent
3. **Write unit tests** → `blockchain-unit-test` agent
4. **E2E validation** → `xlayer-devnet` agent (when requested)

## End-to-End Tests (Devnet)

1. Start multi-node xlayer-devnet with flashblocks enabled
2. Subscribe RPC node to WebSocket flashblocks stream
3. Validate flashblock delivery latency < 250ms
4. Stress test gas/sec throughput under load
5. Measure `engine_newPayload` latency (target: p50 < 50ms)
6. Leader failover: verify `FlashblockPayloadsCache` replay
7. Verify no unintended reorgs across flashblock boundaries
8. Validate P2P propagation between sequencer and follower nodes
9. Test `eth_subscribe("flashblocks")` with address filtering on RPC node
10. Validate pending block state reflects latest flashblocks on consumer nodes
