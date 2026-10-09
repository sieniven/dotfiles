# Fixtures

Seeded cases for agents whose output can be graded against a known answer.
One directory per target; one subdirectory per case:

```
fixtures/<target>/<case>/
  change.md       the task handed to the agent: what the change is meant to do, plus the code
  expected.yaml   verdict, must_find, must_not_flag
```

`expected.yaml`:

```yaml
verdict: FAIL | PASS | PASS-WITH-RISKS      # PASS-WITH-RISKS accepted where listed in also_ok
also_ok: [PASS-WITH-RISKS]                  # optional
must_find:                                  # each must appear as a finding (not a note)
  - id: float-money
    lines: [14, 15]                         # any cited line in range counts
    about: "order size computed in float"
must_not_flag:                              # reporting any of these as a finding fails the case
  - id: cold-path-alloc
    about: "allocation in config loading"
```

Run a case by handing `change.md` to the agent verbatim (the code is inline,
with line numbers), then grade: verdict matches, every `must_find` reported
as a finding citing a line in range, no `must_not_flag` reported as a
finding. A case passes only if all three hold.

## trading-code-reviewer

| Case | Seeded | Tests |
|------|--------|-------|
| `float-money` | order quantity sized with float arithmetic | money rules |
| `swallowed-cancel` | cancel error discarded, quote marked pulled | silent-failure pass |
| `lock-across-await` | mutex guard held across an exchange `.await` | rust concurrency rules |
| `risk-bypass` | new fast path places orders before the risk gate | risk rules |
| `clean-requote` | nothing — a correct requote-threshold change | zero-findings discipline |
| `cold-path-alloc` | nothing — allocations only in config loading | false-positive list |
