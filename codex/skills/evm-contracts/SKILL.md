---
name: evm-contracts
description: Solidity and EVM contract development and security practice. Security properties and a threat model before code, immutability over upgradeability, the Foundry workflow (unit, fuzz, invariant tests with handlers, fork tests, coverage, gas snapshots), static analysis with Slither and Aderyn, property fuzzing with Echidna and Medusa, symbolic checks with Halmos, the vulnerability classes with the detector or test that confirms each (reentrancy, access control and initialization, proxies, oracles, rounding, signatures, MEV, token quirks, ERC-4626, DoS, cross-chain), token-integration and oracle rules, deployment scripts and key hygiene, and the severity matrix and finding schema shared by developer and auditor. Use when writing, testing, reviewing or auditing EVM contracts or their deploy scripts.
---

# EVM contracts

Development and security practice for Solidity on the EVM, including L2s
such as X Layer and OP Stack chains. Solidity style conventions are in
`~/.codex/rules/solidity.md`. The full class list with detectors, confirming
tests and fixes is in `references/vulnerability-classes.md`; commands and
primary sources are in `references/tooling.md`. Solana has its own skill,
`solana-programs`.

## Principles

- Write the security properties first: state machine, access control,
  arithmetic, external interactions, standards conformance. Trail of Bits
  calls this the single most important activity, and every test and audit
  below checks against them.
- Prefer migration over upgradeability, data separation over delegatecall
  proxies, and small on-chain logic with heavy work off-chain. Upgradeability
  is a request to be confirmed, never a default.
- Assume every caller, token, oracle and callback is adversarial. A token
  transfer is an external call; a `view` can be re-entered; `block.timestamp`
  is the sequencer's; a spot AMM price is a flash loan away.
- Code that moves money gets the same discipline as the trading engine: exact
  arithmetic with a stated rounding direction, checked external results,
  events for every state change, and a kill or pause path that cannot be
  bypassed.

## Development workflow

1. Spec: actors and privileges, assets and flows, invariants, parameter
   ranges, arithmetic formulas with expected precision loss, on-chain and
   off-chain assumptions (oracles, bridges, keepers).
2. Threat model against the class list: which classes apply, which do not and
   why.
3. Patterns: OpenZeppelin at a pinned version for access control, SafeERC20,
   ReentrancyGuard, ECDSA, ERC-4626 with a decimals offset; checks-effects-
   interactions; pull over push payments; two-step ownership; `_disableInitializers()`
   in an implementation constructor; namespaced storage (ERC-7201) when
   upgradeable.
4. Implement with the smallest surface: explicit visibility, custom errors,
   immutables, events, no `tx.origin`, no floating pragma on deployables.
5. Tests, in this order: a unit test per branch including every revert
   (`test_RevertWhen_*` with `vm.prank(attacker)` for each guard); fuzz tests
   (`testFuzz_*`) on arithmetic and bounds; invariant tests (`invariant_*`)
   with handler contracts, `bound()`ed inputs and ghost variables, with
   `fail_on_revert` decided deliberately; fork tests for live integrations.
   `forge coverage` to find untested branches; `forge snapshot` for gas.
6. Static analysis: Slither clean or every finding triaged in writing; Aderyn
   as a second opinion; `slither-check-upgradeability` for proxies,
   `slither-check-erc` and `slither-prop` for tokens.
7. Deploy scripts (`script/*.s.sol`) are in scope: constructor arguments,
   ownership transfer, initializer calls, verification. Simulate before
   broadcasting; testnet before mainnet; keys from an encrypted keystore or a
   hardware signer, never a `.env` in the repo.
8. Hand the result to an audit (the `sc-auditor` agent) before calling it done.

## Vulnerability classes, condensed

Each class has a detector or test that confirms it and a fix; the reference
file has them. The condensed list:

- **Reentrancy**: single, cross-function, cross-contract, read-only through a
  `view`; token hooks (ERC777, ERC721, ERC1155) are callbacks.
- **Access control and initialization**: missing modifier, unprotected
  initializer or `_authorizeUpgrade`, `tx.origin`, EOA admin without timelock,
  one-step ownership.
- **Proxies**: storage layout and inheritance order, function shadowing,
  immutables diverging, delegatecall to a no-code address returning true,
  implementation `selfdestruct`, ERC-1967 slots.
- **Oracles**: spot or short-TWAP prices, Chainlink without `updatedAt`,
  `answeredInRound`, bounds, sequencer-uptime and per-feed decimals checks,
  Pyth without confidence and publish time, balance-based pricing.
- **Arithmetic**: division before multiplication, rounding against the
  protocol, downcasts, `unchecked`, decimals mismatch (6 against 18), dust
  rounding to zero, `^` as power.
- **Signatures**: no EIP-712 domain, no nonce or deadline, malleability,
  cross-chain replay, permit front-run griefing, no-op permits (WETH).
- **MEV and ordering**: missing slippage or deadline, initialization
  front-run, approve race, sandwichable liquidations.
- **Token quirks**: missing return (USDT), return-false, approve-to-zero,
  fee-on-transfer, rebasing, blocklists and pauses, upgradeable tokens,
  `>= 2^96` approve reverts, multiple entry points.
- **ERC-4626**: first-depositor inflation, rounding direction, `preview*`
  diverging from execution, `totalAssets` manipulable by donation.
- **DoS**: unbounded loops, push payments to reverting recipients, gas
  limits, forced ETH breaking equality checks.
- **Cross-chain**: message replay without chain id, sender and nonce,
  unvalidated endpoints, finality assumptions, retryable ordering.
- **Centralization**: every privileged role listed, minting and blocklist
  powers, pause traps, upgrade keys without timelock and multisig.
- **Misc**: `abi.encodePacked` collisions, weak randomness, uninitialized
  storage, EIP-6780 `selfdestruct` semantics, metamorphic `create2`, reorgs.

## Rounding rules

Deposits round shares down; withdrawals round assets down; debt rounds up;
fees round up. Test one wei and one share. Multiply before dividing and check
the intermediate for overflow. Never hard-code `1e18` for a token whose
decimals you did not read.

## Severity and finding schema

Shared by the developer's self-review and the auditor's report.

- **Impact**: High is direct loss of user or protocol funds, a permanent
  freeze, or governance takeover. Medium is a temporary denial of service,
  griefing, or value leaking under stated assumptions. Low is a specification
  deviation or hygiene; gas is reported apart.
- **Likelihood**: permissionless with no preconditions; needs a privileged
  actor or an unusual state; needs unrealistic assumptions.
- **FINDING** needs a concrete, unguarded, exploitable path and a `proof:` (an
  executed PoC test). Anything with a partial path or no proof is a **LEAD**,
  kept rather than dropped. One vulnerability per item. The description is
  one active-voice sentence; then attacker, preconditions, steps, impact,
  fix, and confidence (confirmed by PoC, likely, speculative).
- Do not report: admin doing admin things without an unprivileged amplifier,
  `MINIMUM_LIQUIDITY` burns, SafeERC20 where used, `nonReentrant` on a single
  contract (flag only the cross-contract gap), two-step ownership, style.

## Gotchas

1. A guard on one entry point and a sibling entry point without it.
2. An initializer anyone can call, or an implementation left uninitialized.
3. A spot price from the pool being traded against.
4. Rounding that favours the user by one wei, compounded.
5. A `permit` that reverts when front-run.
6. A loop over an array the caller grows.
7. A token that charges a fee, rebases, or returns nothing.
8. A proxy whose storage layout moved by one slot.
9. A deploy script that transfers ownership to the deployer key.
10. A finding without an executed proof reported as confirmed.
