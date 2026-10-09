# Sparse trie and parallel state root

Sections 1–2 of the reth trie skill: sparse trie core types, multiproof revelation, leaf updates, root hashing, trie reuse; multiproof task, proof worker pools, sparse trie task, and the parallel fallback.

## Contents

- [1. Sparse Trie Architecture](#1-sparse-trie-architecture)
  - [Core Types](#core-types)
  - [Multiproof Revelation](#multiproof-revelation)
  - [Leaf Updates](#leaf-updates)
  - [Root Hash Computation](#root-hash-computation)
  - [Trie Reuse Across Blocks](#trie-reuse-across-blocks)
- [2. Parallel State Root Computation](#2-parallel-state-root-computation)
  - [Multiproof Task](#multiproof-task)
  - [Proof Worker Pools](#proof-worker-pools)
  - [MultiProofTargetsV2](#multiprooftargetsv2)
  - [Sparse Trie Task](#sparse-trie-task)
  - [Parallel State Root (Alternative Strategy)](#parallel-state-root-alternative-strategy)

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
