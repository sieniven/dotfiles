# Solana attack classes: look for, confirm, fix

Rows 0 to 10 follow coral-xyz/sealevel-attacks (each directory holds insecure,
recommended and secure variants), read 2026-10-20 [V]; the Trail of Bits and
Neodyme rows were read the same day [V]; the rest is working knowledge. Anchor
constraint names are to be confirmed against the pinned Anchor version.

| # | Class | Look for | Confirm (negative test) | Fix |
|---|---|---|---|---|
| 0 | Signer authorization | an authority account that is not `Signer` / not `is_signer` | call with the authority unsigned | `Signer<'info>`; `is_signer` check |
| 1 | Account data matching | stored pubkey never compared to the passed account | pass a token account owned by someone else | `has_one = authority`; `constraint = token.owner == authority.key()` |
| 2 | Owner check | `AccountInfo` or `UncheckedAccount` read without an owner comparison | pass an account owned by another program with matching layout | `Account<'info, T>`; `account.owner == program_id` |
| 3 | Type cosplay | two account types with the same size and no discriminator | pass a `User` where a `Vault` is expected | Anchor discriminator; explicit type and version fields natively |
| 4 | Initialization | `init_if_needed`; no `is_initialized` flag; initializer callable twice | call initialize twice; initialize over existing data | `init`; `is_initialized` flag; one-time guard |
| 5 | Arbitrary CPI | `invoke`/`invoke_signed` on an unvalidated program account | pass a malicious program id as the token program | `Program<'info, Token>`; compare `program_id` before invoking |
| 6 | Duplicate mutable accounts | two `mut` accounts of one type with no inequality constraint | pass the same account twice | `constraint = a.key() != b.key()` |
| 7 | Bump seed canonicalization | `create_program_address` with a caller-supplied bump; bump not stored | derive a second PDA with a non-canonical bump | `find_program_address`; store the bump; `seeds = [...], bump = state.bump` |
| 8 | PDA sharing | a PDA keyed by a generic prefix shared across users or pools | act on another user's PDA | include the unique identifying key in the seeds |
| 9 | Closing accounts | lamports moved but data left; no discriminator reset | revive the account within the transaction and reuse it | zero data; `close = destination`; closed-account discriminator |
| 10 | Sysvar address checking | a sysvar account read without address validation | pass a fake clock account | `Sysvar<'info, Clock>`; `Clock::get()`; validate the instructions sysvar |
| ToB | Instruction introspection | instructions sysvar read by absolute index | reorder instructions in the transaction | relative indices from the current instruction |
| Neodyme | Integer overflow and truncation | unchecked `+`, `*`, `as` casts | fuzz with `u64::MAX` and negative-equivalent values | `checked_*`, `try_from`; `overflow-checks = true` |
| Neodyme | Account confusion | no type field in a native account struct | pass a differently typed account of equal size | type and version fields; discriminator |
| CPI | Post-CPI stale state | an account read after a CPI without reload | mutate via CPI then read the stale copy | `reload()` after the CPI |
| Tokens | Mint and authority checks | token accounts without `mint`, `owner`, delegate or close-authority checks | pass a token account of another mint | `token::mint = ...`, `token::authority = ...` constraints |
| Token-2022 | Extensions | transfer with fees, hooks, permanent delegate or default state ignored | a mint with a transfer hook or fee | `transfer_checked`; read the mint's extensions; treat hooks as untrusted |
| Oracles | Staleness and confidence | Pyth price without `publish_time`, confidence or feed-id checks; Switchboard without update slot | feed with an old publish time | freshness window, confidence bound, feed id |
| Upgrade | Authority and verification | upgrade authority on a hot key; unverifiable build | inspect `solana program show`; `solana-verify` | multisig or revoked authority; `solana-verify build` |
| Budget | Compute and size | no CU assertion; large stack structs; unbounded `Vec` in an account | LiteSVM/Mollusk `compute_units_consumed`; a stack-overflow build warning | compute-budget request; `Box` or zero-copy; fixed-size accounts |

## Severity cues

Critical: arbitrary CPI with program signer, missing signer or owner check on
a fund-moving path, non-canonical PDA on a vault. High: missing ownership
check elsewhere, sysvar spoofing, reinitialization. Medium: instruction
introspection by absolute index, missing compute budget on a path that can be
made to fail. The EVM skill's finding schema (FINDING with an executed proof,
LEAD otherwise) applies.

## Commands

```
anchor build                      # produces target/deploy/<program>.so; executes nothing
anchor test                       # build + local validator + TS tests; wraps cargo test, see SKILL.md routing
cargo build-sbf                   # replaces cargo build-bpf
CARGO_TARGET_DIR=~/.cache/claude-scratch/target-<checkout> cargo test-sbf
cargo add --dev litesvm           # in-process VM [V]
cargo install trident-cli && trident init && trident fuzz run <fuzz_test>   # [V]
cargo audit ; cargo clippy -- -D warnings
solana-verify build
solana-verify verify-from-repo -u $NETWORK_URL --program-id $PROGRAM_ID https://github.com/$REPO_PATH   # [V]
solana program show $PROGRAM_ID   # upgrade authority
```

Mollusk (anza-xyz/mollusk): `process_instruction`, `process_and_validate_instruction`,
compute-unit benchmarking, fixtures, explicit account list [V]. Surfpool for a
mainnet-fork integration environment. Sec3 X-Ray (sec3-product/x-ray) is a
static analyser whose usage is to be read from its README.

## Primary references

- https://github.com/coral-xyz/sealevel-attacks [V]
- https://github.com/crytic/building-secure-contracts/tree/master/not-so-smart-contracts/solana [V]
- https://neodyme.io/blog/solana_common_pitfalls/ [V] ; https://workshop.neodyme.io [V]
- Solana Foundation program-security course: https://github.com/solana-foundation/developer-content/tree/main/content/courses/program-security [V]
- https://github.com/solana-foundation/solana-verifiable-build [V] ; https://github.com/LiteSVM/litesvm [V] ; https://github.com/anza-xyz/mollusk [V] ; https://github.com/Ackee-Blockchain/trident [V] ; https://github.com/sec3-product/x-ray ; https://github.com/neodyme-labs/solana-security-txt
- Anchor (solana-foundation/anchor) constraints documentation at https://www.anchor-lang.com
