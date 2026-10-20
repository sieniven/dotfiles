# EVM tooling and references

Commands marked [V] were read from the tool's repository on 2026-10-20; the
rest are common usage to confirm with `--help`.

## Foundry

```
forge build
forge test -vvv
forge test --match-test testFuzz_ --fuzz-runs 10000
forge test --match-contract Invariant            # invariant_* tests
forge coverage --report lcov
forge snapshot                                   # gas; --diff / --check in CI
forge test --gas-report
forge script script/Deploy.s.sol --rpc-url $RPC  # simulate; add --broadcast only when asked, --verify after
cast wallet import <name> --interactive          # encrypted keystore; never a plaintext key in .env
```

Invariant testing: `[invariant]` in `foundry.toml` (`runs`, `depth`,
`fail_on_revert`); `invariant_*` functions; `targetContract(handler)` and
`targetSelector`; handlers `bound()` their inputs and keep ghost variables;
read the handler's call and revert summary to confirm coverage.

## Static analysis

```
uv tool install slither-analyzer                          # [V] or pip3 / brew
slither .                                                 # Foundry or Hardhat project
slither . --checklist                                     # markdown report
slither . --print human-summary,contract-summary
slither . --print function-summary,vars-and-auth,inheritance-graph
slither . --detect reentrancy-eth,arbitrary-send-erc20 --exclude-informational
slither-check-upgradeability . MyContractV2 --proxy-name Proxy
slither-check-erc src/Token.sol Token --erc ERC20
slither-prop                                              # ERC20 property tests [V]
cyfrinup                                                  # [V] or brew install cyfrin/tap/aderyn
aderyn .                                                  # report.md, JSON, SARIF
yarn analyze <BASE_PATH> [<SCOPE_FILE>]                   # 4naly3er [V]
semgrep --config p/smart-contracts
```

## Property fuzzing and symbolic execution

```
echidna . --contract Test --config echidna.yaml           # echidna_* properties return bool [V]
echidna . --contract Test --test-mode assertion
go install github.com/crytic/medusa@latest && medusa init # [V]
medusa fuzz [--config medusa.json] [--compilation-target X.sol] [--workers N] [--timeout S] [--test-limit N]   # [V]
uv tool install --python 3.12 halmos                      # [V]
halmos --function check_                                  # symbolic tests prefixed check_ or test_
certoraRun conf.conf                                      # Certora, CVL specs
kontrol build && kontrol prove                            # Runtime Verification
```

## Primary references

- Trail of Bits, building-secure-contracts: https://github.com/crytic/building-secure-contracts [V] (development-guidelines: workflow, guidelines, token_integration, non-standard-tokens, review_checklist, code_maturity, incident_response; program-analysis: slither, echidna, medusa; not-so-smart-contracts)
- Slither and its detector documentation: https://github.com/crytic/slither [V] (`docs/src/detectors/Detector-Documentation.md`)
- Echidna: https://github.com/crytic/echidna ; Medusa: https://github.com/crytic/medusa [V]
- Cyfrin audit checklist (`checklist.json`, Solodit-linked): https://github.com/Cyfrin/audit-checklist [V] ; Aderyn: https://github.com/Cyfrin/aderyn [V]
- 4naly3er: https://github.com/Picodes/4naly3er [V] ; Halmos: https://github.com/a16z/halmos [V]
- Weird ERC-20 catalogue: https://github.com/d-xo/weird-erc20
- OpenZeppelin contracts docs: https://docs.openzeppelin.com/contracts ; Foundry book: https://book.getfoundry.sh
- SWC registry (stale, historical ids): https://github.com/SmartContractSecurity/SWC-registry ; EEA EthTrust Security Levels (its successor): https://github.com/EntEthAlliance/EthTrust-public
- Consensys best practices: https://github.com/Consensys/smart-contract-best-practices ; SCSVS: https://github.com/OWASP/www-project-smart-contract-security-verification-standard
- Findings database: https://solodit.xyz
- Severity wording to confirm before quoting: Code4rena judging criteria, CodeHawks likelihood-by-impact matrix (docs.cyfrin.io/codehawks/findings-severity)
