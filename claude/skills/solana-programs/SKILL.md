---
name: solana-programs
description: Solana on-chain program development and security, Anchor by default and native or Pinocchio when compute units or binary size matter. The account model and its validation (signer, owner, PDA seeds and canonical bump, discriminators, has_one and constraint checks, remaining_accounts, reload after CPI), the sealevel-attacks classes, checked arithmetic, CPI rules, compute-unit and account-size budgets, rent, Token-2022 extensions, versioned transactions, the testing pyramid (LiteSVM and Mollusk, Surfpool, Trident), verifiable builds and upgrade authority, and how program tests must run on this machine. Use when writing, testing, reviewing or auditing Solana programs or their clients' account construction.
---

# Solana programs

Practice for SBF programs. Rust conventions come from `~/.claude/rules/rust.md`;
the attack classes with their checks live in `references/attack-classes.md`;
EVM has its own skill, `evm-contracts`.

## Defaults

- Anchor for a new program; native `solana-program` or Pinocchio when a
  measured compute-unit or binary-size budget demands it. Say which and why.
- Localnet or devnet by default. Mainnet deploys, real-key signing and
  upgrade-authority changes are decisions for the user, never defaults.
- `overflow-checks = true` in the release profile, and checked arithmetic
  anyway: release-mode integer arithmetic wraps and `as` truncates.

## The account model is the attack surface

Assume the attacker controls every account passed to an instruction, every
instruction argument, transaction ordering, and the CPI call graph. Every
account is validated before it is read:

- **Signer**: the authority that approves the action signed the transaction
  (`Signer<'info>`, or `is_signer`).
- **Owner**: the account is owned by the expected program (`Account<'info, T>`
  checks it; native code compares `owner` to the program id).
- **Type**: an 8-byte discriminator or explicit type tag, so one account type
  cannot cosplay as another; a version field when layouts will evolve.
- **Relationships**: `has_one` and `constraint =` against the stored pubkeys
  (the token account's `mint`, `owner`, delegate and close authority; the
  vault's authority).
- **PDAs**: derived with `find_program_address`, the canonical bump stored and
  verified with `seeds` and `bump =`; seeds include a unique identifying key
  so two users never share a PDA; variable-length seeds separated by fixed
  delimiters or length prefixes.
- **Duplicates**: two mutable accounts of the same type are distinct
  (`a.key() != b.key()`).
- **Initialization**: `init` (not `init_if_needed` unless the guard is
  explicit) or an `is_initialized` flag; reinitialization is an attack.
- **Closing**: zero the data, move the lamports, and let the discriminator
  defend against revival within the same transaction (`close =`).
- **Sysvars**: `Sysvar::get()` or `Sysvar<'info, Clock>`, never an
  unvalidated sysvar account; instruction introspection by relative index.
- **remaining_accounts** get every check a typed account would; after any
  CPI the mutated accounts are `reload()`ed before being trusted.

## CPI

- Validate the program id of every program invoked (`Program<'info, Token>`
  or an explicit comparison) before `invoke` or `invoke_signed`; an arbitrary
  CPI with the program's PDA signer is a complete compromise.
- Do not pass signer privileges implicitly to an unvalidated program; CPI
  depth is four; return data is the callee's claim, not a fact.
- Token-2022 extensions change token behaviour the way ERC-20 quirks do:
  transfer fees, transfer hooks (untrusted code runs inside your transfer),
  permanent delegates, confidential transfers, default account state. Use
  `transfer_checked`, check the mint's extensions, and never hard-code rent.

## Budgets and limits

- 200k compute units per instruction by default, 1.4M per transaction,
  raised via the compute-budget program; measure with LiteSVM or Mollusk
  (`compute_units_consumed`) and record the number beside the instruction.
- Stack frame 4 KB, heap 32 KB: large structs go behind `Box` or zero-copy
  (`#[account(zero_copy)]`, `repr(C)`, `bytemuck`), and recursion is avoided.
- Account data up to 10 MiB, realloc up to 10 KiB per instruction, rent
  exemption from `Rent::minimum_balance(size)`; no unbounded `Vec` growth
  inside an account.
- Versioned transactions with address lookup tables add accounts but lookup
  table accounts cannot sign; never assume account order or count is fixed.

## Oracles and external state

Pyth: check staleness (`publish_time`), the confidence interval and the feed
id. Switchboard: the update slot. Any price with no freshness check is a
finding.

## Testing

- Pyramid: LiteSVM or Mollusk for fast in-process unit tests of instructions
  (explicit account lists, fixtures, compute-unit assertions); Surfpool or a
  local validator for integration against a mainnet fork; Trident or
  `cargo-fuzz` for fuzzing; `cargo audit` and `cargo clippy -- -D warnings`.
- Every validation above has a negative test: wrong signer, wrong owner,
  wrong mint, cosplayed account, non-canonical bump, duplicate account,
  double initialize, revived account, spoofed sysvar, wrong CPI target.
- **On this machine**: LiteSVM, Mollusk and `cargo test-sbf` tests are
  `cargo test` binaries. In a main checkout under `~/dev` the bash guard
  denies plain `cargo test`, and `cargo test-sbf` and `anchor test` are not
  caught by the guard but write fresh test executables to the checkout's
  `target/`, which the endpoint-security sensor may refuse. Run them with
  `CARGO_TARGET_DIR=~/.cache/claude-scratch/target-<checkout> cargo test-sbf ...`
  (one target dir per checkout root) or from a linked worktree, as the
  machine-local section of the global CLAUDE.md prescribes. `anchor build`
  produces a `.so` and executes nothing; `anchor test` wraps a build, a local
  validator and the test suite (confirm what it runs for the pinned Anchor
  with `anchor test --help` before relying on it), so pass the same target dir
  through `CARGO_TARGET_DIR` and name any refused target as unverified, never
  passed.

## Deployment and upgrades

- Program upgrade authority sits with a multisig or is revoked; the choice
  is written down. `solana-verify build` and `verify-from-repo` so the
  deployed bytecode matches the source. A `security.txt` in the program.
- Admin instructions are guarded by signer and state, not by convention.
- Simulate before sending; the client code reads keys from a keystore or
  signer service, never from a file in the repo.

## Gotchas

1. A missing owner check lets a forged account pass `has_one`.
2. A non-canonical bump creates a second valid PDA.
3. `init_if_needed` without a guard is a reinitialization attack.
4. Two mutable accounts that are the same account.
5. An unvalidated CPI target called with the program's signer seeds.
6. Wrapping arithmetic in release mode and `as` casts that truncate.
7. A closed account revived in the same transaction.
8. A transfer hook that runs attacker code inside your instruction.
9. A test suite that never asserts a compute-unit budget.
10. A refused test binary counted as a pass.
