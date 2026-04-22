---
name: reth-trie
description: Expert knowledge of reth's Merkle Patricia Trie system — sparse trie,
  parallel state root computation, multiproof pipeline, deferred trie data, overlay
  system, and changeset cache. Use for understanding, debugging, or modifying state
  root computation, proof generation, trie persistence, and reorg support in reth.
---

# Reth Trie System Skill

You are an expert in reth's Merkle Patricia Trie (MPT) system, with deep knowledge of how state root computation, proof generation, trie persistence, and overlay management work end-to-end. This skill covers the full trie pipeline: from block execution producing hashed state, through parallel multiproof generation, sparse trie updates, state root verification, deferred trie sorting, overlay construction, and changeset caching for reorg support.

---

## Repository

| Path | Role |
|---|---|
| `~/dev/xlayer/op-stack/xlayer/reth/` | Reth execution client (upstream) |

Key crate paths (all relative to `reth/crates/`):

- `trie/sparse/` — Sparse trie core implementation
- `trie/parallel/` — Parallel state root and proof worker pools (`ProofWorkerHandle`, `ProofTaskCtx`)
- `trie/common/` — Shared trie types (`TrieInput`, `HashedPostState`, `TrieUpdates`, `DecodedMultiProof`)
- `trie/db/` — Database-backed trie cursors and changeset cache
- `trie/trie/` — Walker, proof, hash builder, `TrieNodeIter`
- `engine/tree/src/tree/payload_processor/` — Sparse trie task, multiproof task, prewarm task, payload orchestration
- `engine/tree/src/tree/payload_processor/prewarm.rs` — Speculative tx execution + `PrefetchProofs` dispatch
- `engine/tree/src/tree/payload_validator.rs` — Block validation entry point, state root strategy
- `chain-state/src/` — `DeferredTrieData`, `LazyOverlay`, `ExecutedBlock`
- `storage/provider/src/providers/state/overlay.rs` — `OverlayStateProviderFactory`

For a detailed end-to-end workflow walkthrough, see [workflow.md](workflow.md).

---

## End-to-End Pipeline Overview

```
Block arrives (newPayload from CL)
  |
  v
validate_block_with_state()                    [payload_validator.rs:339-650]
  |
  +-- 1. Plan StateRootStrategy                [payload_validator.rs:1255-1263]
  |       - StateRootTask: multiproof + sparse trie (production)
  |       - Parallel: parallel state root on calling thread (fallback)
  |       - Synchronous: serial computation (testing)
  |
  +-- 2. Create OverlayStateProviderFactory    [payload_validator.rs:440-447]
  |       - Wraps DB provider + LazyOverlay (in-memory ancestor state)
  |       - Provides composite state view for proof workers
  |
  +-- 3. Spawn PayloadProcessor                [payload_processor/mod.rs:144-431]
  |       - Transaction iterator task (sig recovery via rayon)
  |       - Prewarm + Multiproof task (proof target dispatch)
  |       - Sparse trie task (applies proofs, computes root)
  |
  +-- 4. Execute block transactions
  |       - Each tx triggers state_hook() -> MultiProofMessage::StateUpdate
  |       - Proof targets generated from changed accounts/storage
  |
  +-- 5. State root computation completes
  |       - StateRootComputeOutcome { state_root, trie_updates }
  |       - Verify: state_root == block.header().state_root()
  |
  +-- 6. Spawn deferred trie task              [payload_validator.rs:1343-1463]
  |       - Background: sort hashed state + trie updates
  |       - Build cumulative TrieInputSorted overlay
  |       - Compute + cache trie changesets for reorg
  |
  +-- 7. Return ExecutedBlock immediately
          - Deferred trie data computed asynchronously
          - Consumers get data via wait_cloned() (async or sync fallback)
```

---

## 1. Sparse Trie Architecture

### Core Types

**`SparseStateTrie<A, S>`** — `trie/sparse/src/state.rs:36-62`
- Orchestrates account trie + storage tries
- `state: RevealableSparseTrie<A>` — account trie (blind until root revealed)
- `storage: StorageTries<S>` — `B256Map<RevealableSparseTrie<S>>`
- `revealed_account_paths: HashSet<Nibbles>` — tracks which accounts have proofs
- `deferred_drops: DeferredDrops` — buffers expensive deallocations
- `retain_updates: bool` — whether to track node insertions/deletions
- `skip_proof_node_filtering: bool` — optimization for reused tries

**`ParallelSparseTrie`** — `trie/sparse/src/parallel.rs:105-132`
- Hierarchical 2-level trie for parallel hash computation:
  - `upper_subtrie: Box<SparseSubtrie>` — root paths (< 2 nibbles depth)
  - `lower_subtries: Box<[LowerSparseSubtrie; 16]>` — 16 parallel subtries
- `prefix_set: PrefixSetMut` — tracks modified paths for incremental rehashing
- `branch_node_masks: BranchNodeMasksMap` — tree_mask/hash_mask per branch node
- `subtrie_heat: SubtrieModifications` — hot/cold tracking for smart pruning
- `updates: Option<SparseTrieUpdates>` — conditional update tracking

**`SparseSubtrie`** — `trie/sparse/src/parallel.rs:2444+`
- Single subtrie: `path: Nibbles`, `nodes: HashMap<Nibbles, SparseNode>`, values map

**`SparseNode`** — `trie/sparse/src/trie.rs:334-378`
- `Empty` — empty trie root
- `Hash(B256)` — blinded node (only hash known, not revealed)
- `Leaf { key, hash }` — leaf with remaining key suffix
- `Extension { key, hash, store_in_db_trie }` — path compression node
- `Branch { state_mask, hash, store_in_db_trie }` — 16-way branch

**`RevealableSparseTrie<T>`** — `trie/sparse/src/trie.rs:23-39`
- `Blind(Option<Box<T>>)` — not yet revealed; may carry pre-allocated cleared trie for reuse
- `Revealed(Box<T>)` — root revealed, full trie operations available

### Multiproof Revelation

Multiproofs are the mechanism by which trie nodes are loaded into the sparse trie from proof workers.

**`reveal_decoded_multiproof()`** — `state.rs:273-354`
- Decodes legacy multiproof, reveals account + storage trees
- Filters already-revealed nodes to avoid redundant work
- Pushes proof node buffers to `DeferredDrops` for deferred cleanup

**`reveal_decoded_multiproof_v2()`** — `state.rs:367-453`
- V2 format: proof nodes stored as vectors with embedded masks
- Two paths based on `skip_proof_node_filtering`:
  - `true`: Pass all nodes directly (reused tries handle dedup internally)
  - `false`: Filter already-revealed nodes

**`ParallelSparseTrie::reveal_nodes()`** — `parallel.rs:178-362`
- Sorts nodes by subtrie, separates upper vs lower
- Upper nodes: processed serially (small)
- Lower nodes: parallel via rayon (if threshold exceeded), grouped by subtrie index
- Checks reachability from upper subtrie parent branch for boundary leaves

### Leaf Updates

**`ParallelSparseTrie::update_leaf()`** — `parallel.rs:364-427+`
- Check if value exists in upper or lower subtrie values map → in-place update
- Otherwise: insert into upper subtrie, traverse to correct position
- May move to lower subtrie during traversal
- Updates `prefix_set` to mark path dirty for rehashing
- Returns blinded path info if a `Hash` node is encountered (needs proof)

**`SparseTrie::update_leaves()`** — `traits.rs:326-331`
- Batch applies `B256Map<LeafUpdate>` to trie
- For blind tries: removes all updates, emits proof targets
- For revealed tries: applies what it can, keeps blocked updates, emits targets for blinded paths

### Root Hash Computation

**`ParallelSparseTrie::root()`** — `parallel.rs:897-917`
1. Fast path: `prefix_set.is_empty()` + root has cached hash → return immediately
2. `update_subtrie_hashes()` — parallel: rayon over dirty lower subtries
3. `update_upper_subtrie_hashes()` — serial: uses lower subtrie root hashes
4. Extract root hash from updated root node

**`SparseStateTrie::root_with_updates()`** — `state.rs:888-906`
- Ensures account trie is revealed
- Calls `trie.root()` (triggers incremental hash update via prefix_set)
- Calls `take_updates()` — combines account + storage trie updates
- Returns `(B256, TrieUpdates)`

### Trie Reuse Across Blocks

**`PreservedSparseTrie`** — `payload_processor/preserved_sparse_trie.rs:51-115`
- Two states:
  - `Anchored { trie, state_root }` — computed root, reuse if parent matches
  - `Cleared { trie }` — data cleared, allocations preserved
- `into_trie_for(parent_state_root)`:
  - If anchored + state root matches parent → full structural reuse (no re-reveal needed)
  - Otherwise → clear and return (allocation reuse only)

**`SharedPreservedSparseTrie`** — `preserved_sparse_trie.rs:16-31`
- `Arc<Mutex<Option<PreservedSparseTrie>>>` — shared between blocks
- `take()`: Get trie for next block; `lock()`: Block take until result ready

---

## 2. Parallel State Root Computation

### Multiproof Task

**`MultiProofTask`** — `payload_processor/multiproof.rs:691-753`
- Event loop using `crossbeam::select!` on two channels:
  - **Control channel** (`rx`): `PrefetchProofs`, `StateUpdate`, `EmptyProof`, `FinishedStateUpdates`
  - **Proof result channel** (`proof_result_rx`): `ProofResultMessage` from workers

**Dual Input Sources** (concurrent with execution):

- **Prewarm task** → `PrefetchProofs`: speculative proof targets from parallel tx execution on stale state (runs ahead of real execution)
- **Block executor** → `StateUpdate`: authoritative per-tx state diffs via `state_hook()` (sequential)

**Message Flow**:
```
Prewarm (speculative) --PrefetchProofs--> MultiProofTask
Execution (per-tx state_hook) --StateUpdate--> MultiProofTask
                                                  |
                              +-------------------+
                              | get_proof_targets()
                              | dedup vs fetched_proof_targets
                              v
                     If all targets already fetched:
                       EmptyProof (zero worker cost)
                     Else:
                       dispatch_account_multiproof()
                              |
                              v
                     ProofWorkerHandle --jobs--> Worker Pools
                              |
                              v
                     ProofResultMessage (multiproof + sequence_number)
                              |
                              v
                     ProofSequencer::add_proof() -- reorder in-order -->
                              |
                              v
                     to_sparse_trie.send(SparseTrieUpdate)
```

**Proof Sequencer** — `multiproof.rs:132-180`
- Ensures sparse trie updates applied in transaction order despite workers returning out-of-order
- `BTreeMap<u64, SparseTrieUpdate>` buffer for out-of-order results
- Delivers consecutive sequence numbers when available

### Proof Worker Pools

**`ProofWorkerHandle`** — `trie/parallel/src/proof_task.rs:102-398`
- Two independent pools:
  - `storage_work_tx` → storage proof workers (spawn_blocking via rayon)
  - `account_work_tx` → account proof workers (spawn_blocking via rayon)
- `*_available_workers: Arc<AtomicUsize>` — tracks idle worker count
- Workers use `ProofTaskCtx<Factory>` with database cursors for trie traversal

**Worker Flow** (account worker, `build_account_multiproof_with_storage_roots()`):

1. Each worker holds a **read-only DB transaction** opened at startup against the pre-block state (`OverlayStateProviderFactory`). All workers see the same immutable trie — no race conditions.
2. **Fan out storage proofs**: dispatch storage proof jobs to the storage worker pool for all target accounts, receiving `CrossbeamReceiver` handles back immediately.
3. **Full sorted trie scan** via `TrieNodeIter` (merges `TrieWalker` + `HashedCursor`):
   - `TrieWalker` scans persisted intermediate nodes (`BranchNodeCompact`) in lexicographic order
   - `HashedCursor` scans hashed accounts table in lexicographic order
   - At each branch: if subtree is unchanged (hash flag set, no prefix_set match) → yield `TrieElement::Branch(key, hash)` (skip entire subtree)
   - Otherwise descend and yield `TrieElement::Leaf(hashed_address, account)`
4. **Feed into `HashBuilder`** (from `alloy_trie`) with a `ProofRetainer`:
   - `Branch` → `hash_builder.add_branch(key, hash, ...)` — reuse pre-computed hash as-is
   - `Leaf` → block on storage proof receiver for storage_root, encode `TrieAccount{nonce, balance, storage_root, code_hash}` as RLP, then `hash_builder.add_leaf(path, rlp)`
   - `HashBuilder` processes the sorted stream and computes hashes when it moves past a subtree prefix (all entries under that prefix have been seen)
   - `ProofRetainer` captures intermediate trie nodes along target account paths
5. Call `hash_builder.root()` to finalize, then `take_proof_nodes()` to extract `DecodedProofNodes`
6. Send `ProofResultMessage { sequence_number, result: ProofResult(DecodedMultiProof), state }` back via crossbeam channel

**Important**: The `HashBuilder` reconstructs the **pre-block** trie structure to extract proof nodes. It does NOT compute post-transaction hashes. The actual new state root is computed later by the sparse trie.

### MultiProofTargetsV2

**`MultiProofTargetsV2`** — `trie/parallel/src/targets_v2.rs:7-31`
- `account_targets: Vec<Target>` — account proof targets with min_len
- `storage_targets: B256Map<Vec<Target>>` — per-account storage targets
- Supports chunking for parallel dispatch across workers

### Sparse Trie Task

**`SparseTrieTask`** — `payload_processor/sparse_trie.rs:101-211`
- Simple variant: receives `SparseTrieUpdate` via mpsc, applies to trie
- `run()`: drain updates → `update_sparse_trie()` each batch → `root_with_updates()`

**`SparseTrieCacheTask`** — `payload_processor/sparse_trie.rs:216-277`
- Advanced variant with trie caching and incremental proof fetching
- Maintains: `account_updates`, `storage_updates`, `pending_account_updates`
- Dispatches proof targets on-demand via `ProofWorkerHandle`

**`update_sparse_trie()`** — `sparse_trie.rs:895-1045`
1. Reveal multiproof (V1 or V2) into sparse trie
2. Storage updates (parallel via rayon): update leaves, compute storage roots
3. Account updates: encode TrieAccount with storage root, update account trie leaves
4. Account removals: remove_account_leaf()
5. Calculate subtrie hashes

### Parallel State Root (Alternative Strategy)

**`ParallelStateRoot`** — `trie/parallel/src/root.rs:23-221`
- Used when `StateRootStrategy::Parallel` is selected (no sparse trie)
- Spawns blocking tasks for each modified account's storage root
- Walks account trie with `TrieWalker` + `HashBuilder`
- Simpler but slower than multiproof-based approach for many accounts

---

## 3. Deferred Trie Data

### Purpose

After state root verification, `HashedPostState` and `TrieUpdates` are unsorted. Multiple consumers need sorted data:
- **DB persistence**: sorted for efficient B-tree insertion
- **Proof generation**: next block needs `TrieInputSorted` overlay from in-memory ancestors
- **RPC overlay queries**: serving state from unpersisted blocks

Sorting is CPU-intensive but **not needed for validation**, so it runs in a background `spawn_blocking` task.

### DeferredTrieData

**`DeferredTrieData`** — `chain-state/src/deferred_trie.rs:20-23`
- `state: Arc<Mutex<DeferredState>>` — Pending (unsorted inputs) or Ready (computed result)

**`PendingInputs`** — `deferred_trie.rs:79-89`
- `hashed_state: Arc<HashedPostState>` (unsorted)
- `trie_updates: Arc<TrieUpdates>` (unsorted)
- `anchor_hash: B256` (persisted ancestor reference)
- `ancestors: Vec<DeferredTrieData>` (ancestor handles for overlay merging)

**`ComputedTrieData`** — `deferred_trie.rs:29-36`
- `hashed_state: Arc<HashedPostStateSorted>`
- `trie_updates: Arc<TrieUpdatesSorted>`
- `anchored_trie_input: Option<AnchoredTrieInput>` — cumulative overlay + anchor hash

### Computation: `sort_and_build_trie_input()`

**`sort_and_build_trie_input()`** — `deferred_trie.rs:160-259`

All work is purely in-memory (no DB reads):
1. Sort `HashedPostState` + `TrieUpdates` (parallel via rayon)
2. Check parent's cached `anchored_trie_input`:
   - **Fast path (O(1))**: anchor matches → clone parent's `Arc`-wrapped overlay, extend with current block's sorted data (COW via `Arc::make_mut`)
   - **Slow path**: anchor mismatch or no cached overlay → `merge_ancestors_into_overlay()` rebuilds from all ancestors
3. Return `ComputedTrieData` with `AnchoredTrieInput` for child blocks to reuse

### Access: `wait_cloned()`

**`wait_cloned()`** — `deferred_trie.rs:314-349`
- Lock mutex, check state:
  - `Ready` → return cached result (common case if background task finished)
  - `Pending` → compute synchronously from stored inputs, cache as `Ready`
- **No deadlock**: ancestors form a DAG (each block only waits on its ancestors, never siblings or descendants)
- Metrics track async-ready vs sync-fallback ratio

### Spawning

**`spawn_deferred_trie_task()`** — `payload_validator.rs:1343-1463`
1. Collect lightweight `trie_data_handle()` refs from ancestor `ExecutedBlock`s
2. Create `DeferredTrieData::pending(unsorted_hashed_state, unsorted_trie_updates, anchor, ancestors)`
3. Spawn background task that calls `wait_cloned()` (triggers sort + overlay build)
4. Same task also computes trie changesets and inserts into changeset cache
5. Return `ExecutedBlock::with_deferred_trie_data(block, output, deferred_handle)` immediately

---

## 4. Overlay System

### LazyOverlay

**`LazyOverlay`** — `chain-state/src/lazy_overlay.rs:34-39`
- `inner: Arc<OnceLock<TrieInputSorted>>` — computed on first access
- `inputs: LazyOverlayInputs { anchor_hash, blocks: Vec<DeferredTrieData> }`

**Computation** — `lazy_overlay.rs:91-138`
- **Fast path**: tip block's cached `anchored_trie_input` exists + anchor matches → reuse directly (O(1))
- **Slow path**: merge all blocks' trie data via `HashedPostStateSorted::merge_batch()` + `TrieUpdatesSorted::merge_batch()`
- Result cached in `OnceLock` — first call computes, subsequent calls return cached

### OverlayStateProviderFactory

**`OverlayStateProviderFactory`** — `storage/provider/src/providers/state/overlay.rs:89-143`
- `factory: F` — underlying DB provider factory
- `block_hash: Option<B256>` — revert target
- `overlay_source: Option<OverlaySource>` — `Lazy(LazyOverlay)` or `Immediate`
- `changeset_cache: ChangesetCache` — trie revert lookup

**State Layering for Proof Workers**:
```
+-------------------------------------------+
| Worker's Database Provider View           |
+-------------------------------------------+
              ^
    +---------+----------+
    |                    |
    v                    v
+------------------+  +------------------+
| LazyOverlay      |  | Database State   |
| (in-memory)      |  | (at anchor hash) |
| - Block N state  |  | Persisted data   |
| - Block N+1 ...  |  | + Changeset      |
| - Block N+k      |  |   cache          |
| (parent)         |  |                  |
+------------------+  +------------------+
```

### TrieInput / TrieInputSorted

**`TrieInput`** (unsorted) — `trie/common/src/input.rs:10-137`
- `nodes: TrieUpdates` — cached intermediate trie nodes
- `state: HashedPostState` — in-memory hashed account/storage changes
- `prefix_sets: TriePrefixSetsMut` — changed paths

**`TrieInputSorted`** — `trie/common/src/input.rs:144-171`
- `nodes: Arc<TrieUpdatesSorted>` — sorted trie updates
- `state: Arc<HashedPostStateSorted>` — sorted hashed state
- `prefix_sets: TriePrefixSetsMut`
- Pre-sorted + Arc-wrapped for efficient sharing across blocks

---

## 5. Changeset Cache

### Purpose

Caches trie changesets (old node values before a block) for efficient reorg/revert support. When a reorg occurs, reth needs the old trie node values to revert to the pre-block state.

### ChangesetCache

**`ChangesetCache`** — `trie/db/src/changesets.rs:253-510`
- `Arc<RwLock<ChangesetCacheInner>>`
- Inner:
  - `entries: B256Map<(u64, Arc<TrieUpdatesSorted>)>` — block_hash -> (block_number, old_node_values)
  - `block_numbers: BTreeMap<u64, Vec<B256>>` — for ordered eviction

**API**:
- `get(block_hash)` — lookup by block hash (metrics: hit/miss)
- `insert(block_hash, block_number, changesets)` — add to cache
- `evict(up_to_block)` — remove blocks below threshold (after persistence)
- `get_or_compute(block_hash, block_number, provider)` — try cache, fallback to DB computation
- `get_or_compute_range(provider, range)` — accumulate changesets for block range (for reorg revert), newest-to-oldest so older values take precedence

### Changeset Computation

**`compute_block_trie_changesets()`** — `trie/db/src/changesets.rs:61-141`
1. Get individual state revert for block N
2. Get cumulative state revert for block N-1 (db tip -> after N-1)
3. Compute cumulative trie updates revert for N-1
4. Create prefix sets from block N's individual revert
5. Build overlay with cumulative trie updates (N-1) + cumulative state (N)
6. Compute new trie updates using overlay
7. Diff against N-1 overlay to get old node values (changesets)

### Population

In `spawn_deferred_trie_task()` (payload_validator.rs:1418-1434):
- After sorting trie data, the same background task computes changesets
- Uses `overlay_factory.database_provider_ro()` for DB access
- Inserts result into `changeset_cache` for future reorg support

---

## 6. Key Data Types

### HashedPostState / HashedPostStateSorted

**`HashedPostState`** (unsorted) — `trie/common/src/hashed_state.rs:29-35`
- `accounts: B256Map<Option<Account>>` — hashed address -> account (None = destroyed)
- `storages: B256Map<HashedStorage>` — hashed address -> storage changes

**`HashedPostStateSorted`** — `hashed_state.rs:546-620`
- `accounts: Vec<(B256, Option<Account>)>` — sorted by hashed address
- `storages: B256Map<HashedStorageSorted>` — per-account sorted storage
- `extend_ref_and_sort()` — merge another sorted state, re-sort combined

### TrieUpdates / TrieUpdatesSorted

**`TrieUpdates`** (unsorted) — `trie/common/src/updates.rs:17-87`
- `account_nodes: HashMap<Nibbles, BranchNodeCompact>` — intermediate branch nodes
- `removed_nodes: HashSet<Nibbles>` — deleted branch node paths
- `storage_tries: B256Map<StorageTrieUpdates>` — per-account storage trie changes

**`TrieUpdatesSorted`** — `updates.rs:550-628`
- `account_nodes: Vec<(Nibbles, Option<BranchNodeCompact>)>` — sorted (None = removed)
- `storage_tries: B256Map<StorageTrieUpdatesSorted>` — per-account sorted

### ExecutedBlock

**`ExecutedBlock`** — `chain-state/src/in_memory.rs:753-900`
- `recovered_block: Arc<RecoveredBlock<N::Block>>`
- `execution_output: Arc<BlockExecutionOutput<N::Receipt>>`
- `trie_data: DeferredTrieData`
- Key methods:
  - `trie_data()` — calls `wait_cloned()`, may block if async pending
  - `trie_data_handle()` — lightweight clone of handle (no computation)
  - `hashed_state()` / `trie_updates()` — convenience accessors

---

## 7. State Root Strategies

### StateRootTask (Production)

```
PayloadProcessor::spawn()
  |
  +-- TxIteratorTask: parallel signature recovery
  +-- PrewarmTask + MultiProofTask: proof target dispatch
  +-- SparseTrieTask: applies proofs, computes root
```

- Proofs fetched concurrently with execution
- Each transaction's state changes generate proof targets
- Out-of-order proofs resequenced before sparse trie application
- Sparse trie computes root incrementally as proofs arrive
- Trie can be preserved and reused across consecutive blocks

### Parallel (Fallback)

**`ParallelStateRoot`** — `trie/parallel/src/root.rs:23-221`
- Direct trie walker approach (no sparse trie or multiproofs)
- Spawns blocking tasks for modified accounts' storage roots
- Walks account trie with `TrieWalker` + `HashBuilder`
- Simpler but no incremental computation or trie reuse

### Synchronous (Testing)

- Serial computation via state provider
- No background tasks
- `compute_state_root_serial()` in payload_validator.rs

---

## 8. Key Invariants and Design Decisions

1. **Deferred trie data never blocks validation**: The state root is verified using the sparse trie. Sorting/overlay construction happens asynchronously after validation.

2. **Anchor hash guards overlay reuse**: An overlay built on anchor A cannot be reused for a block anchored to B. The `AnchoredTrieInput.anchor_hash` field enforces this invariant.

3. **DAG-based deadlock freedom**: `wait_cloned()` can recursively wait on ancestors, but since blocks form a DAG (never circular), deadlock is impossible.

4. **DeferredDrops avoids allocation jitter**: Proof node buffers are collected during multiproof revelation and dropped after root computation, keeping the critical path allocation-free.

5. **Prefix set tracks dirty paths**: Only paths in the prefix set are rehashed during `root()`, enabling O(changed) rather than O(total) hash computation.

6. **COW overlay extension**: Parent overlays are extended via `Arc::make_mut()` (copy-on-write), so the common case (single consumer) avoids cloning entirely.

7. **Proof sequencer preserves ordering**: Despite parallel proof generation, sparse trie updates are applied in transaction execution order to ensure deterministic state roots.

8. **`Arc::try_unwrap` optimization**: When sorting deferred data, if only one reference to the Arc exists, it moves the data in-place instead of cloning.

9. **Workers are read-only against pre-block state**: All proof workers share the same `OverlayStateProviderFactory` snapshot opened at block start. They never see each other's results or post-transaction state. This eliminates race conditions — overlapping trie paths from different workers simply produce duplicate proof nodes that are deduplicated at reveal time by `revealed_account_paths`.

10. **New intermediate hashes computed once, at the end**: Proof workers extract pre-block trie structure (existing nodes). The sparse trie applies all leaf updates, then computes all new intermediate hashes in a single pass during `root()`. No intermediate hashes are computed speculatively or in parallel across workers.

---

## 9. Common Debugging Patterns

### Metrics to Monitor

- `sync.block_validation.deferred_trie_async_ready` — background task finished before consumer needed data (good)
- `sync.block_validation.deferred_trie_sync_fallback` — consumer needed data before background task finished (indicates bottleneck)
- `sparse_trie_update_duration_histogram` — time per sparse trie update batch
- `sparse_trie_final_update_duration_histogram` — time for final root_with_updates()
- `sparse_trie_total_duration_histogram` — total sparse trie task time
- `deferred_trie_compute_duration` — sorting + overlay build time

### Tracing Targets

- `engine::tree::payload_validator` — block validation flow
- `engine::tree::payload_processor::sparse_trie` — sparse trie task
- `engine::tree::deferred_trie` — deferred trie computation
- `engine::root` — root calculation iterations

### Common Issues

- **State root mismatch**: Check if multiproof workers have correct overlay (anchor hash match), verify proof sequencer ordering
- **Slow deferred trie**: High sync_fallback count means background task too slow; check rayon thread pool saturation
- **Overlay reuse failure**: Anchor hash changed (persistence happened); expected during normal operation, frequent occurrence may indicate suboptimal persistence timing
- **Changeset cache misses**: Check eviction threshold vs reorg depth
