---
name: onchain-execution
description: The client side of trading through a chain from a low-latency service, on EVM chains (Ethereum, OP Stack L2s such as X Layer, Arbitrum, Base) and Solana. An intent journal written before broadcast and reconciled from chain on restart, nonce authority per address and replacement rules, EIP-1559 fee prediction with hard caps and L2 data fees, simulation and revert decoding before every send, confirmation depth and reorg handling, private order flow and approval hygiene, provider lag and chain-id checks, and on Solana blockhash expiry, compute budget and priority fees, rebroadcast until expiry, commitment consistency, lookup tables and Jito bundles. Keys outside the strategy process behind a policy-enforcing signer with a kill switch at sign time. Use when writing or reviewing code that builds, signs, sends, tracks or reconciles transactions, or that streams chain state into a trading engine.
---

# On-chain execution

A chain is a venue: the exchange-boundary rules in `quant-trading` apply
(untrusted replies, reconcile from the venue, rate budgets, never local
state alone). Contract-side rules live in `evm-contracts` and
`solana-programs`; read them when the client touches a contract interface.
Library facts, commands and the primary references are in
`references/libraries.md`.

## The intent journal

- Every action is an intent with its own id; the journal maps an intent to
  its attempts (chain, signer, nonce or blockhash, raw hash or signature, fee
  parameters) and its state: created, signed, sent, seen pending,
  confirmed(n), finalized, dropped, replaced, failed on chain. Transitions
  are explicit and terminal states are final.
- The signed raw bytes are written to the journal, durably, before broadcast,
  so a restart rebroadcasts the same transaction instead of signing a second
  one. No second attempt for an intent until the first is terminal by chain
  evidence; a send timeout is "in flight", never "failed".
- On restart: load the journal, then reconcile from chain (EVM transaction
  counts latest against pending, receipts by hash, a scan by sender and
  nonce; Solana signature statuses against the blockhash height) and treat
  the chain as truth. Balances and allowances reconcile on a timer with
  drift alerts.

## EVM

### Nonces
- One signer, one nonce authority, one queue per address; parallelism comes
  from more addresses, never from out-of-order nonces on one.
- Initialise from the pending transaction count, increment locally, resync
  from chain after any failed send, reorg or restart. A cached nonce manager
  never resyncs itself.
- "Nonce too low" means already used: reconcile against the journal before
  retrying. "Nonce too high" means a gap: a lower nonce is missing or dropped
  and blocks everything behind it.
- Replacement reuses the nonce with both fee caps raised by at least ten
  percent; a cancel is a zero-value self-transfer at the higher fee, after
  which the original may still win, so reconcile.

### Fees
- Max fee about twice the predicted base fee plus the tip, under a hard
  per-chain cap that rejects rather than clips; base fee predicted from fee
  history (the next block's value is the last entry; at most 12.5 percent
  change per block); gas limit from an estimate times a headroom factor,
  capped; a per-chain floor and ceiling in config.
- OP Stack charges an L1 data fee outside gas units, deducted from the
  sender's ETH balance; read it from the gas-price oracle and include it in
  cost checks and balance alerts. Arbitrum folds its L1 component into gas
  units, so add margin for L1 price movement between estimate and inclusion.
- A chain that reports a base fee but rejects type-2 transactions needs the
  legacy fee path chosen explicitly; the default filler will not fall back.

### Simulation and reverts
- Simulate the exact calldata, sender and block before every send, with
  state overrides for inventory not yet funded; decode `Error(string)`,
  `Panic(uint256)` and the ABI's custom errors by selector; trace the
  failing frame when the reason is opaque.
- A passing simulation says nothing about inclusion later: slippage and a
  deadline in the calldata, and a fresh simulation on every retry.

### Confirmation and reorgs
- A mined transaction with status zero paid gas and failed: a failed intent,
  not a pending one. Confirmation depth is per-chain config; OP Stack heads
  are unsafe (sequencer, reorderable), safe (derived from L1) or finalized,
  queried by tag, never assumed from `latest`.
- Subscriptions record the last processed block number and hash, detect a
  reorg by parent-hash mismatch, roll the journal back past the fork point,
  and on reconnect backfill logs from the last block minus a reorg margin,
  deduplicating by block hash and log index.

### Ordering and approvals
- Swaps on L1 go through a private endpoint; on single-sequencer L2s the
  sequencer controls ordering. Minimum output from a fresh quote and a
  deadline in seconds; bundles are simulated before submission.
- Approvals are exact or bounded per swap, re-read before use, never
  unlimited on a hot wallet; permit-style signatures carry a short expiry.

### Providers
- Chain id checked against config at startup and on every reconnect, and
  carried inside every signed transaction; signing refuses on a mismatch.
- Behind a load balancer `latest` can go backwards: reads pinned to a block
  hash or number, head height checked monotonic, at least two providers
  compared and the lagging one dropped; log queries chunked to the provider's
  range limit; rate-limit responses mean backoff and a provider switch, not a
  failed intent; raw transactions sent to several providers (idempotent) and
  state read from a node you trust.

## Solana

### Transaction lifecycle
- A blockhash is valid for about 150 blocks: keep the last valid block
  height, compare with the current height, and treat expiry as the only
  evidence that a transaction is dropped. Rebroadcast the identical signed
  bytes until then (node retries off, your own loop on), re-check once after
  expiry, and only then rebuild with a fresh blockhash; rebuilding earlier
  double-executes.
- Blockhash, simulation and reads at one commitment, with a minimum context
  slot on reads so a lagging node cannot answer from the past. Preflight
  skipped only after your own simulation.
- Every transaction sets a compute-unit limit (simulated units plus ten to
  twenty percent) and a compute-unit price estimated from recent
  prioritisation fees on the writable accounts, at a percentile and under a
  hard cap. Packets are 1232 bytes: version-0 messages and lookup tables when
  the account list grows, remembering tables need a slot to warm after
  extension.
- Durable nonces for long-lived or offline-signed transactions, advance
  first and one nonce per in-flight transaction. Bundles (up to five
  transactions with a tip in the last) for atomic ordering; staked or
  direct-to-leader submission when landing rate matters.

### State and accounts
- Program-account scans never on a hot path; narrow filters or an indexer,
  and a gRPC account stream for latency, reconnected from the last slot and
  deduplicated by slot and write version.
- Associated token accounts created idempotently with rent budgeted; wrapped
  SOL synced and closed explicitly; a mint's token program and extensions
  read before deriving accounts, with transfer-hook extra accounts resolved
  client-side.

## Keys and risk

- No private key in the strategy process: a signer service, KMS or HSM that
  enforces policy (allowed chains, contracts or programs, selectors or
  discriminators, maximum value, fee and notional per transaction and per
  hour) and a kill switch checked at signing time with a cancel-all mode.
- One hot wallet per strategy with a capped balance and a separate funding
  key; separate keys per chain and per Solana cluster; nothing signed that
  was not simulated.
- Alerts on stuck nonce age, pending count, expired-blockhash rate, drop
  rate, spend per hour and provider head lag.

## Testing

- EVM: a forked local node pinned to a block, impersonated accounts for
  funding, time warps for deadlines, the real client path exercised
  including replacement and revert decoding, and recorded RPC exchanges
  replayed through a fault-injecting proxy (drops, delays, stale heads).
- Solana: an in-process VM for client logic, a local validator with cloned
  accounts for realism, and an explicit expiry test proving no double
  execution.

## Gotchas

1. A mined transaction with status zero, or a Solana status with an error.
2. A cached nonce after a failed send or reorg.
3. A replacement with only one fee cap raised; a stuck nonce blocking an address.
4. L2 data fees outside gas units and outside the estimate.
5. `latest` from a lagging node; an unsafe head taken as final.
6. A simulation trusted past the next block.
7. An unchecked chain id, or a legacy-fee chain behind a type-2 filler.
8. A Solana transaction rebuilt before its blockhash expired.
9. Commitment mismatch between build, simulate and read; a default compute budget.
10. A key in the strategy process, an unlimited approval, a kill switch that stops sending but not signing.
