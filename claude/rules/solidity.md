---
paths:
  - "**/*.sol"
---

# Solidity conventions

Loaded automatically whenever a `.sol` file is read or edited; the auditor
reads it explicitly when reviewing a diff. Deviations from textbook defaults
only; the security classes, tooling and finding schema live in the
`evm-contracts` skill.

## Pragma and layout

- Deployable contracts pin an exact compiler version (`pragma solidity 0.8.x;`);
  libraries and interfaces may float within a minor. Match the repo's
  `foundry.toml` `solc_version`, `evm_version` and `optimizer_runs`.
- One contract per file; file name equals contract name; `forge fmt` clean.
- Order: pragma, imports, errors, events, type declarations, state, modifiers,
  constructor, receive and fallback, external, public, internal, private; view
  and pure last within each group.

## Safety

- Checks, effects, interactions: state is final before any external call,
  including token transfers, which are external calls with hooks.
- Explicit visibility on everything; `immutable` and `constant` for values set
  once; `private` by default with `internal` where inheritance needs it.
- Custom errors, not revert strings; one event per state change with indexed
  keys the indexers need.
- No `tx.origin`, no `selfdestruct`, no `block.timestamp` as randomness, no
  `abi.encodePacked` with more than one dynamic argument, no `delegatecall` to
  a caller-controlled address.
- `unchecked` blocks carry a comment stating why overflow is impossible.
  Downcasts go through `SafeCast`. Multiply before dividing, and the rounding
  direction is named in a comment.
- SafeERC20 for every token interaction; `forceApprove` (OpenZeppelin 5; on 4.x
  `safeIncreaseAllowance` after approve-to-zero) for USDT-style tokens;
  balance-delta accounting when fee-on-transfer is possible. Every OpenZeppelin
  name here is the one at the version the repo pins.
- Two-step ownership (`Ownable2Step`) and role-based access from the pinned
  OpenZeppelin; `_disableInitializers()` in an upgradeable implementation's
  constructor; ERC-7201 namespaced storage for upgradeable state.

## Documentation

- NatSpec on every external and public function and on every custom error:
  `@notice` for what it does, `@param`, `@return`, and `@dev` for the
  invariant or rounding it relies on.
- A header comment per contract naming the actors, the privileged roles and
  the invariants the tests pin.

## Tests

- Names: `test_<Function>_<Scenario>`, `test_RevertWhen_<Condition>`,
  `testFuzz_<Function>`, `invariant_<Property>`; one behaviour per test.
- Every guard has a `test_RevertWhen_*` under `vm.prank(attacker)` that
  asserts the custom error with `vm.expectRevert(Selector.selector)`.
- Handlers for invariant tests `bound()` their inputs and keep ghost
  variables; `fail_on_revert` is a deliberate choice written in the test.
- No `console.log` in `src/`; deploy scripts in `script/` are reviewed as code.
