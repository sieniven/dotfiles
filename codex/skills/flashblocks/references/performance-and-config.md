# Flashblocks performance and configuration

Optimization areas (sequencer gas/s, RPC execution speed, trie and merklization), CLI argument reference, and key dependencies.

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
