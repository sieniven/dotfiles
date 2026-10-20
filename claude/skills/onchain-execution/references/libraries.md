# Libraries, commands and references

Facts marked [V] were read from the library's repository on 2026-10-20 (alloy
changelog and fillers, the Agave changelog, LiteSVM and Yellowstone READMEs,
the OP Stack execution-engine spec); the rest is working knowledge to confirm
against the pinned version, which for client libraries changes often.

## alloy (Rust, the current Ethereum client stack; ethers-rs is deprecated [V])

- `NonceFiller` wraps a `NonceManager` and defaults to `CachedNonceManager`;
  it keeps a nonce already set on the request and needs `from` set [V].
  `SimpleNonceManager` asks the node for the pending count every call (safe
  across reorgs, collides under concurrent sends); `CachedNonceManager`
  advances a per-address counter before broadcast and never resyncs after a
  failed send, a reorg or another manager's send [V]. Resync explicitly.
- `GasFiller` fills EIP-1559 fees when both are unset and `gas_limit` from an
  estimate when unset; it falls back to a legacy gas price only when the
  latest header has no base fee, so chains that report a base fee but reject
  type-2 transactions need `GasFiller::legacy()` [V]. Custom estimators via
  `GasFiller::new(estimator)` [V]; blob fees through `BlobGasFiller` [V].
- Send and confirm: `send_transaction` returns a pending-transaction builder
  with required confirmations, timeout, `get_receipt()` and `watch()` (which returns the hash, not the receipt); check
  the receipt status yourself. Simulation through `call` with `.block()` and
  `.overrides()`, and `simulate` for `eth_simulateV1`. Subscriptions need a
  pubsub transport (`connect_ws(WsConnect)` or IPC, `pubsub` feature); HTTP polls. Revert decoding through `sol!`-generated `SolError` types
  (`Error(string)` selector `0x08c379a0`, `Panic(uint256)` `0x4e487b71`).
  Signers: local key, AWS KMS, GCP, Ledger, Trezor, YubiHSM crates. Fork
  tests through `alloy-node-bindings` spawning anvil. Confirm builder and
  method names against the pinned 2.x release.

## Other EVM clients (confirm names per version)

viem (`createPublicClient`, `createWalletClient`, `simulateContract`,
`writeContract`, `waitForTransactionReceipt`, `estimateFeesPerGas`, nonce
manager, `fallback` and `webSocket` transports); web3.py v7 and eth-account
(`get_transaction_count(addr, "pending")`, `build_transaction`,
`estimate_gas`, `sign_transaction`, `send_raw_transaction`,
`wait_for_transaction_receipt`; set every field yourself on a hot path).

## Solana clients

- Agave is the validator; its server-side crates are an unstable API from
  v4.0 and must not be client dependencies [V]. v4.4 adds `minContextSlot` to
  `getTransaction` and `getSignatureStatuses` and honours `dataSlice` on
  account subscriptions [V].
- The client crates are split (`solana-pubkey`, `solana-keypair`,
  `solana-transaction`, `solana-message`, `solana-compute-budget-interface`,
  `solana-system-interface`), `solana-sdk` remaining as a partial re-export facade, with `solana-rpc-client` for RPC; the
  non-blocking `RpcClient` offers `send_transaction_with_config`
  (`skip_preflight`, `preflight_commitment`, `max_retries`,
  `min_context_slot`), `simulate_transaction_with_config`,
  `get_signature_statuses`, `get_latest_blockhash_with_commitment` (hash and
  last valid block height), `get_recent_prioritization_fees`,
  `is_blockhash_valid`; `send_and_confirm_transaction` polls and is not for a
  latency path; `TpuClient` sends to leaders over QUIC. Confirm crate names on
  crates.io.
- Compute budget: `ComputeBudgetInstruction::set_compute_unit_limit(u32)`,
  `set_compute_unit_price(u64)` in micro-lamports; priority fee equals price
  times limit over a million lamports on top of the 5000-lamport signature
  fee. Version-0 messages via `v0::Message::try_compile` with lookup tables
  and `VersionedTransaction::try_new`; durable nonces advance first.
- Python: solders types plus solana-py's async client and `TxOpts`;
  TypeScript: `@solana/kit` (confirm its 2.x API).
- LiteSVM: in-process VM with `airdrop`, `latest_blockhash`,
  `send_transaction`, `simulate_transaction`, `add_program`, `set_account`
  [V]. Yellowstone gRPC streams accounts, transactions, slots and blocks with
  owner, size and memcmp filters, account data slices and a ping keepalive
  [V]. `solana-test-validator --clone` for realistic accounts.

## Commands

```
anvil --fork-url $RPC --fork-block-number N --chain-id 31337     # pinned fork
cast rpc anvil_impersonateAccount 0x...                         # fund from a whale
cast rpc evm_increaseTime 3600 && cast rpc evm_mine
cast call --rpc-url $RPC --block pending $TO $CALLDATA           # simulate
cast estimate --rpc-url $RPC $TO $CALLDATA
cast 4byte-decode 0x...                                          # revert selector
solana-test-validator --url $RPC --clone $ACCOUNT --clone-upgradeable-program $PROGRAM --reset
solana confirm -v $SIGNATURE
solana program show $PROGRAM_ID
```

## Primary references

- alloy: https://github.com/alloy-rs/alloy [V] ; https://alloy.rs ; https://docs.rs/alloy
- EVM: EIP-1559 https://eips.ethereum.org/EIPS/eip-1559 ; JSON-RPC https://ethereum.github.io/execution-apis ; OP Stack specs (L1 data fee, unsafe/safe/finalized) https://specs.optimism.io [V] ; Arbitrum docs https://docs.arbitrum.io ; Flashbots https://docs.flashbots.net ; anvil https://book.getfoundry.sh/anvil ; Permit2 https://github.com/Uniswap/permit2
- viem https://viem.sh ; web3.py https://web3py.readthedocs.io ; eth-account https://eth-account.readthedocs.io
- Solana: transactions https://solana.com/docs/core/transactions ; retry and expiry https://solana.com/developers/guides/advanced/retry ; fees https://solana.com/docs/core/fees ; RPC https://solana.com/docs/rpc ; Agave https://github.com/anza-xyz/agave [V] ; rpc client https://docs.rs/solana-rpc-client ; solders https://github.com/kevinheavey/solders ; solana-py https://github.com/michaelhly/solana-py ; LiteSVM https://github.com/litesvm/litesvm [V] ; Yellowstone https://github.com/rpcpool/yellowstone-grpc [V] ; Jito https://docs.jito.wtf ; priority fee API https://www.helius.dev/docs/priority-fee-api ; SPL https://github.com/solana-labs/solana-program-library
