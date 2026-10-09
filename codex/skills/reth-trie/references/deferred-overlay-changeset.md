# Deferred trie data, overlays, changesets, types and strategies

Sections 3–7 of the reth trie skill: `DeferredTrieData`, the overlay system, the changeset cache, key data types, and state root strategies.

## Contents

- [3. Deferred Trie Data](#3-deferred-trie-data)
  - [Purpose](#purpose)
  - [DeferredTrieData](#deferredtriedata)
  - [Computation: `sort_and_build_trie_input()`](#computation-sort_and_build_trie_input)
  - [Access: `wait_cloned()`](#access-wait_cloned)
  - [Spawning](#spawning)
- [4. Overlay System](#4-overlay-system)
  - [LazyOverlay](#lazyoverlay)
  - [OverlayStateProviderFactory](#overlaystateproviderfactory)
  - [TrieInput / TrieInputSorted](#trieinput--trieinputsorted)
- [5. Changeset Cache](#5-changeset-cache)
  - [Purpose](#purpose)
  - [ChangesetCache](#changesetcache)
  - [Changeset Computation](#changeset-computation)
  - [Population](#population)
- [6. Key Data Types](#6-key-data-types)
  - [HashedPostState / HashedPostStateSorted](#hashedpoststate--hashedpoststatesorted)
  - [TrieUpdates / TrieUpdatesSorted](#trieupdates--trieupdatessorted)
  - [ExecutedBlock](#executedblock)
- [7. State Root Strategies](#7-state-root-strategies)
  - [StateRootTask (Production)](#stateroottask-production)
  - [Parallel (Fallback)](#parallel-fallback)
  - [Synchronous (Testing)](#synchronous-testing)

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
