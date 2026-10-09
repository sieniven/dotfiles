---
name: reth-trie
description: "Expert knowledge of reth's Merkle Patricia Trie system \u2014 sparse trie, parallel state root computation, multiproof pipeline, deferred trie data, overlay system, and changeset cache. Use for understanding, debugging, or modifying state root computation, proof generation, trie persistence, and reorg support in reth."
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

## Reference files

Load the file that matches the task; each is one level deep from here.

| File | Read when |
|---|---|
| [references/sparse-trie-and-parallel-root.md](references/sparse-trie-and-parallel-root.md) | Sections 1–2: sparse trie internals, multiproof task, proof workers, sparse trie task, parallel fallback |
| [references/deferred-overlay-changeset.md](references/deferred-overlay-changeset.md) | Sections 3–7: deferred trie data, overlays, changeset cache and reorgs, key data types, state root strategies |
| [workflow.md](workflow.md) | Stage-by-stage walkthrough of the multiproof pipeline, end to end |

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
