# Multiproof Pipeline: End-to-End Workflow

This document traces the full lifecycle of how reth computes the state root for a block, from transaction execution through proof worker dispatch, sparse trie updates, and final hash computation. It covers the concurrency model, data flow, and correctness invariants.

---

## Stage 0: Spawn — All Components Start Concurrently

`PayloadProcessor::spawn()` ([payload_processor/mod.rs:323-432]) starts everything at once:

```
PayloadProcessor::spawn()
  |
  +-- 1. spawn_tx_iterator()        → rayon: parallel signature recovery
  |       Splits tx stream into (prewarm_rx, execution_rx)
  |
  +-- 2. spawn_caching_with()       → PrewarmCacheTask on blocking thread
  |       Receives prewarm_rx, executes txs speculatively
  |       Sends PrefetchProofs to MultiProofTask
  |
  +-- 3. ProofWorkerHandle::new()   → Two rayon worker pools
  |       Account workers + Storage workers (dedicated DB transactions)
  |
  +-- 4. MultiProofTask::new()      → Event loop on blocking thread
  |       Receives PrefetchProofs + StateUpdate messages
  |       Dispatches work to proof worker pools
  |
  +-- 5. spawn_sparse_trie_task()   → SparseTrieTask on blocking thread
  |       Receives SparseTrieUpdate from MultiProofTask
  |       Computes final state root
  |
  +-- Returns PayloadHandle { state_hook, state_root_rx, ... }
```

All five components run on separate threads from the start. The prewarm task and proof workers begin working **before** the real block executor starts its first transaction.

---

## Stage 1: Proof Target Generation (Concurrent with Execution)

Two independent sources feed proof targets to the `MultiProofTask`:

### Source A: Prewarm Task — Speculative Prefetch

The prewarm task speculatively executes transactions on **stale state** (results may be incorrect). For each transaction, it extracts the accounts/slots touched and sends `PrefetchProofs`:

```rust
// prewarm.rs:639-644 — inside prewarm worker after speculative tx execution
if index > 0 {
    let (targets, storage_targets) =
        multiproof_targets_from_state(res.state, v2_proofs_enabled);
    if let Some(to_multi_proof) = &to_multi_proof {
        let _ = to_multi_proof.send(MultiProofMessage::PrefetchProofs(targets));
    }
}
```

This is a **prediction**: "transaction N will probably touch these accounts/slots, start fetching proofs now." Runs ahead of real execution, giving proof workers a head start.

### Source B: Real Block Execution — Authoritative State Updates

The sequential block executor calls `state_hook()` after each transaction commits:

```rust
// mod.rs:870-878
pub fn state_hook(&self) -> impl OnStateHook {
    let to_multi_proof = self.to_multi_proof.clone().map(StateHookSender::new);
    move |source: StateChangeSource, state: &EvmState| {
        if let Some(sender) = &to_multi_proof {
            let _ = sender.send(MultiProofMessage::StateUpdate(source.into(), state.clone()));
        }
    }
}
```

This sends the **real** state diff per transaction. `StateHookSender` sends `FinishedStateUpdates` on drop (when execution completes).

### Timeline

```
Time ──────────────────────────────────────────────────────────►

Prewarm (parallel, speculative):
  tx0 ──► PrefetchProofs({acct_A, acct_B})
  tx1 ──► PrefetchProofs({acct_C, slot_X})
  tx2 ──► PrefetchProofs({acct_A, acct_D})

              Both feed into ──► MultiProofTask

Real Execution (sequential, authoritative):
  tx0 ──► StateUpdate({acct_A, acct_B})     ← likely already prefetched
  tx1 ──► StateUpdate({acct_C, slot_X})     ← likely already prefetched
  tx2 ──► StateUpdate({acct_A, acct_E})     ← acct_E may be new
```

---

## Stage 2: MultiProofTask — Deduplication and Dispatch

The `MultiProofTask` ([multiproof.rs:691-753]) runs an event loop using `crossbeam::select_biased!` on two channels:

- **Control channel** (`rx`): `PrefetchProofs`, `StateUpdate`, `EmptyProof`, `FinishedStateUpdates`
- **Proof result channel** (`proof_result_rx`): `ProofResultMessage` from workers

`select_biased!` prioritizes proof results over new requests to prevent worker starvation.

### Deduplication

For every incoming message, the task checks `fetched_proof_targets` — a map of all accounts/slots already dispatched:

```rust
// multiproof.rs:877-889 — on_hashed_state_update()
let (fetched_state_update, not_fetched_state_update) = hashed_state_update
    .partition_by_targets(&self.fetched_proof_targets, &self.multi_added_removed_keys);

// Already fetched → EmptyProof (no worker dispatch needed)
if !fetched_state_update.is_empty() {
    self.tx.send(MultiProofMessage::EmptyProof {
        sequence_number: self.proof_sequencer.next_sequence(),
        state: fetched_state_update,
    });
}

// New targets → dispatch to workers
// ... calls self.multiproof_manager.dispatch(...)
```

If the prewarm guess was correct, most `StateUpdate` targets are already fetched — they become `EmptyProof` (zero worker cost).

### Sequence Numbers

Every dispatch (whether `EmptyProof` or worker job) gets a monotonically increasing `sequence_number` from `ProofSequencer`. This preserves transaction execution order for the sparse trie.

### Chunking

Large target sets can be split across multiple workers via `dispatch_with_chunking()`, based on available workers and a configurable `max_targets_for_chunking` threshold (default: 300).

---

## Stage 3: Account Proof Workers — Full Trie Scan

### What Workers Read

Each worker opens a **read-only database transaction** at startup:

```rust
// proof_task.rs:867-868
let provider = self.task_ctx.factory.database_provider_ro()?;
```

The `factory` is an `OverlayStateProviderFactory` providing a **composite view**: persisted DB state + in-memory overlay from unpersisted ancestor blocks. All workers see the **same pre-block trie** — purely read-only.

### The Trie Scan

The account worker does NOT traverse a single root-to-leaf path. It performs a **full sorted scan** of the entire account trie, interleaving two DB cursors:

1. **`TrieWalker`** — scans persisted intermediate trie nodes (`BranchNodeCompact`) in lexicographic order
2. **`HashedCursor`** — scans hashed accounts table (nonce, balance, code_hash) in lexicographic order

`TrieNodeIter` merges these streams. At each branch, the walker decides: **can I skip this subtree?**

- **Yes** (hash flag set + no prefix_set match): yield `TrieElement::Branch(key, hash)` — entire subtree unchanged, reuse cached hash
- **No** (prefix_set has entries under this branch): descend into subtree, yield individual leaves

For a trie with 1M accounts and 3 modified, the vast majority is skipped as `Branch` elements.

### The HashBuilder

The `HashBuilder` (from `alloy_trie`) consumes this sorted stream and reconstructs the trie:

```rust
// proof_task.rs:1605-1699
while let Some(account_node) = account_node_iter.try_next()? {
    match account_node {
        TrieElement::Branch(node) => {
            // Pre-computed hash from DB — subtree unchanged, record as-is
            hash_builder.add_branch(node.key, node.value, node.children_are_in_trie);
        }
        TrieElement::Leaf(hashed_address, account) => {
            // 1. Block on storage proof receiver for this account's storage root
            let root = receiver.recv()?.result?.root();

            // 2. Encode TrieAccount {nonce, balance, storage_root, code_hash}
            let account = account.into_trie_account(root);
            account.encode(&mut account_rlp);

            // 3. Feed leaf into HashBuilder
            hash_builder.add_leaf(Nibbles::unpack(hashed_address), &account_rlp);
        }
    }
}
let _ = hash_builder.root();
let proof_nodes = hash_builder.take_proof_nodes();
```

The `HashBuilder` works as a **streaming trie builder**:
- Entries arrive in sorted key order (guaranteed by `TrieWalker` + `HashedCursor`)
- When the builder moves past a prefix, all entries under that prefix have been seen
- At that point it assembles and hashes the branch node for that subtree
- The `ProofRetainer` (configured with target account paths) captures intermediate nodes along target paths

**The HashBuilder computes hashes of the PRE-BLOCK trie, not the post-block trie.** Its purpose is to reconstruct enough trie structure to extract proof nodes. The actual new state root is computed later by the sparse trie.

### Interleaved Storage Proof Parallelism

Before starting the account trie walk, the account worker fans out storage proof jobs:

```rust
// proof_task.rs:1313-1319
let storage_proof_receivers = dispatch_storage_proofs(
    &self.storage_work_tx, &targets, &mut storage_prefix_sets, ...
)?;
```

Storage workers compute storage proofs in parallel on a separate rayon pool. During the account trie walk, when the walker encounters a leaf (account), the account worker **blocks on that specific account's storage proof receiver**:

```rust
let root = match storage_proof_receivers.remove(&hashed_address) {
    Some(receiver) => {
        let proof_msg = receiver.recv()?;  // block on this one account
        // ... extract storage root
    }
    None => { /* compute inline or use cache */ }
};
```

This is **interleaved parallelism**: the account trie walk proceeds for accounts that don't need storage proofs, and only blocks when it encounters one that does. Storage workers have time to complete while the account walk processes other entries.

### Output: ProofResultMessage

```rust
pub struct ProofResultMessage {
    pub sequence_number: u64,                                    // for ordering
    pub result: Result<ProofResult, ParallelStateRootError>,     // proof nodes
    pub elapsed: Duration,
    pub state: HashedPostState,                                  // original state diff
}
```

The `ProofResult` contains a `DecodedMultiProof`:
- `account_subtree: DecodedProofNodes` — path → TrieNode map for the account trie
- `storages: B256Map<DecodedStorageMultiProof>` — per-account storage proof nodes
- `branch_node_masks: BranchNodeMasksMap` — tree_mask/hash_mask per branch node

---

## Stage 4: Proof Nodes — What They Are

A "proof node" is a **decoded MPT trie node** at a specific path. `DecodedProofNodes` is a `HashMap<Nibbles, TrieNode>`:

```rust
// From alloy_trie — the three MPT node types
enum TrieNode {
    Branch { ... },     // 16-way branch with child hashes
    Extension { ... },  // path-compression node (key prefix + child)
    Leaf { ... },       // terminal node (remaining key suffix + value)
}
```

For a target account `0xAB...`, the proof nodes would be every trie node along the path from root to that leaf:

```
Path []    → Branch(root)
Path [A]   → Extension or Branch
Path [A,B] → Leaf(RLP(TrieAccount))
```

Nodes on unrelated paths remain as opaque `Hash(B256)` values within branch nodes — the proof doesn't reveal their internal structure.

---

## Stage 5: ProofSequencer — Reordering

Workers return results out of order. The `ProofSequencer` ([multiproof.rs:132-180]) buffers them and delivers in sequence:

```rust
fn add_proof(&mut self, sequence: u64, update: SparseTrieUpdate) -> Vec<SparseTrieUpdate> {
    if sequence == self.next_to_deliver {
        // Fast path: in-order delivery
        let mut consecutive = vec![update];
        self.next_to_deliver += 1;
        // Drain any buffered consecutive proofs
        while let Some(pending) = self.pending_proofs.remove(&self.next_to_deliver) {
            consecutive.push(pending);
            self.next_to_deliver += 1;
        }
        return consecutive;
    }
    // Out of order: buffer it
    self.pending_proofs.insert(sequence, update);
    Vec::new()
}
```

Only consecutive sequences are forwarded to the sparse trie via `to_sparse_trie.send()`.

---

## Stage 6: Sparse Trie — Revelation, Leaf Updates, and Root Computation

The `SparseTrieTask` receives `SparseTrieUpdate { state, multiproof }` messages and processes them via `update_sparse_trie()` ([sparse_trie.rs:895-1045]):

### Step 1: Reveal Proof Nodes

```rust
// Reveal account proof nodes into the sparse trie
sparse_trie.reveal_decoded_multiproof(multiproof)?;
```

This calls `reveal_decoded_account_multiproof()` ([state.rs:467-507]) which:

1. **Filters already-revealed nodes** via `revealed_account_paths` — if path `[A]` was revealed by a previous proof, it's skipped (deduplication for overlapping proofs)
2. **Reveals root node** if not yet revealed (first proof for this block)
3. **Reveals remaining nodes** into the sparse trie's node map

Each `TrieNode` becomes a `SparseNode`:
- `TrieNode::Branch` → `SparseNode::Branch { state_mask, hash, ... }`
- `TrieNode::Extension` → `SparseNode::Extension { key, hash, ... }`
- `TrieNode::Leaf` → `SparseNode::Leaf { key, hash }`

Paths NOT in the proof remain as `SparseNode::Hash(B256)` — **blinded** nodes where only the hash is known.

### Step 2: Update Storage Trie Leaves

For each account with storage changes, update the storage trie leaves with new values, then compute the new storage root:

```
For each (hashed_address, storage_changes):
  1. Reveal storage proof nodes into account's storage trie
  2. Update storage slot leaves with new values
  3. Compute new storage root via storage_trie.root()
```

Storage updates run in parallel via rayon when there are many accounts.

### Step 3: Update Account Trie Leaves

For each modified account:

```
1. Get the new storage root (from step 2, or EMPTY_ROOT_HASH)
2. Encode TrieAccount { nonce, balance, storage_root, code_hash } as RLP
3. Update the account trie leaf at the hashed address
```

The leaf update marks the path as **dirty** in the `prefix_set`.

### Step 4: Handle Account Removals

For self-destructed accounts, remove the leaf node entirely.

### Handling Overlapping Proofs

When two transactions modify accounts whose trie paths intersect (e.g., accounts `0xAB...` and `0xAC...` sharing branch `[A]`), correctness is maintained because:

1. **Workers read the same pre-block DB snapshot** — both return the same branch node at `[A]`
2. **Deduplication at reveal time** — `revealed_account_paths` prevents double-revealing the same node
3. **Sequential leaf updates** — the `ProofSequencer` ensures updates arrive in tx order
4. **Single root computation** — hashes are recomputed once at the end, not during revelation

Example with overlapping paths:
```
Worker 1 (tx1, modifies 0xAB): returns Branch([A]) + Leaf([A,B])
Worker 2 (tx2, modifies 0xAC): returns Branch([A]) + Leaf([A,C])

Sparse trie after revealing both:
  [A]   → Branch (revealed once, deduped)
  [A,B] → Leaf (revealed, then updated with tx1's value)
  [A,C] → Leaf (revealed, then updated with tx2's value)
```

---

## Stage 7: Final Root Hash Computation

After all proofs are revealed and all leaves updated, the sparse trie computes the root:

### `ParallelSparseTrie::root()` ([parallel.rs:897-917])

```
1. Check prefix_set — if empty and root hash cached, return immediately (no changes)
2. update_subtrie_hashes() — parallel via rayon over 16 lower subtries
   - Only rehash subtries with dirty paths in prefix_set
   - Each subtrie: walk bottom-up, RLP-encode nodes, keccak256 hash
3. update_upper_subtrie_hashes() — serial, uses lower subtrie root hashes
4. Extract root hash from root node
```

### How Intermediate Hashes Are Computed

An **intermediate hash** is the `keccak256` of a non-leaf trie node's RLP encoding. During `root()`:

1. **Leaf nodes**: `hash = keccak256(RLP(Leaf(remaining_key, value)))` — computed from the updated value
2. **Extension nodes**: `hash = keccak256(RLP(Extension(key, child_hash)))` — uses child's new hash
3. **Branch nodes**: `hash = keccak256(RLP(Branch(child_0_hash, ..., child_15_hash)))` — assembles all children
4. **Blinded `Hash` nodes**: reused as-is — these subtrees weren't modified

Only paths in the `prefix_set` (dirty paths) are rehashed. Clean subtrees retain their cached hashes. This makes root computation `O(changed_paths)` rather than `O(total_trie_size)`.

### `SparseStateTrie::root_with_updates()` ([state.rs:888-906])

Returns `(B256, TrieUpdates)`:
- `B256` — the new state root
- `TrieUpdates` — all intermediate node insertions/deletions for DB persistence

---

## Stage 8: Verification and Completion

```rust
// payload_validator.rs — after execution completes
let outcome = handle.state_root()?;  // blocks until sparse trie finishes
assert_eq!(outcome.state_root, block.header().state_root());
```

If the state root matches, the block is valid. The `TrieUpdates` are passed to the deferred trie task for sorting, overlay construction, and changeset caching.

---

## Complete Data Flow Diagram

```
                    ┌─────────────────────────────────┐
                    │     PayloadProcessor::spawn()    │
                    └───┬────────┬────────┬───────────┘
                        │        │        │
          ┌─────────────┘        │        └──────────────────┐
          ▼                      ▼                           ▼
  ┌───────────────┐    ┌─────────────────┐         ┌────────────────┐
  │  Prewarm Task │    │ Block Executor  │         │ ProofWorkerPool│
  │  (speculative)│    │  (sequential)   │         │ (account+stor) │
  └───────┬───────┘    └────────┬────────┘         └───────▲────────┘
          │                     │                          │
  PrefetchProofs          StateUpdate              dispatch jobs
          │                     │                          │
          ▼                     ▼                          │
  ┌─────────────────────────────────────────┐              │
  │           MultiProofTask                │──────────────┘
  │  - dedup vs fetched_proof_targets       │
  │  - assign sequence numbers              │
  │  - dispatch to workers OR EmptyProof    │
  │  - receive ProofResultMessage           │
  │  - ProofSequencer reorders              │
  └──────────────────┬──────────────────────┘
                     │
            SparseTrieUpdate (in tx order)
                     │
                     ▼
  ┌──────────────────────────────────────────┐
  │           SparseTrieTask                 │
  │  1. reveal_decoded_multiproof()          │
  │     - filter already-revealed nodes      │
  │     - convert TrieNode → SparseNode      │
  │     - blinded paths stay as Hash(B256)   │
  │  2. Update storage leaves + roots        │
  │  3. Update account leaves (with storage  │
  │     roots from step 2)                   │
  │  4. root_with_updates()                  │
  │     - rehash only dirty paths            │
  │     - parallel over 16 lower subtries    │
  │     - return (state_root, trie_updates)  │
  └──────────────────┬───────────────────────┘
                     │
                     ▼
          StateRootComputeOutcome
          { state_root, trie_updates }
                     │
                     ▼
          Verify: state_root == header.state_root
```

---

## Key Correctness Invariants

1. **Workers are read-only against pre-block state**: All proof workers share the same `OverlayStateProviderFactory` snapshot. They never see each other's results or the real execution's state changes. This eliminates race conditions.

2. **Proof node deduplication at reveal time**: `revealed_account_paths` in the sparse trie tracks which paths have been revealed. Overlapping proofs from different workers are deduplicated — the same branch node is only revealed once.

3. **Transaction ordering via ProofSequencer**: Despite workers returning out of order, `ProofSequencer` ensures sparse trie updates arrive in the same order as transaction execution. This guarantees deterministic state roots.

4. **Prefix set tracks dirty paths**: Only modified paths are rehashed during `root()`. Clean subtrees (represented as `SparseNode::Hash`) retain their pre-computed hashes.

5. **New intermediate hashes computed once, at the end**: Proof workers extract pre-block trie structure. The sparse trie applies all leaf updates, then computes all new intermediate hashes in a single pass during `root()`. No intermediate hashes are computed speculatively or in parallel across workers.

6. **EmptyProof fast path**: When the prewarm correctly predicted the targets, `StateUpdate` targets are already in `fetched_proof_targets`. The update becomes an `EmptyProof` — zero worker dispatch, just a state diff forwarded to the sparse trie.
