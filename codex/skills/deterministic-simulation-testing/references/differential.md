# Differential testing against a reference

Companion to `SKILL.md`. Not from the article: this is a method for code
that has a reference implementation or a recorded truth to agree with, such
as a node fork against upstream, a codec against captures, or a rewritten
engine component against the one it replaces. Simulation finds interleavings;
differential testing finds where two implementations disagree on the same
input.

## Record a corpus with its provenance

- Inputs and the reference's outputs, recorded once: blocks and their
  commitments, RPC requests and answers, venue captures, golden fixtures.
- Each entry records where it came from: the source (endpoint, node, file),
  the reference's version or commit, and the date. A fixture without
  provenance cannot be re-recorded or trusted when it disagrees.
- Cases whose answers depend on time, the gateway or the reference's own
  local state are marked as such and skipped, never compared.

## Replay and stop at the first mismatch

- Run the implementation over the corpus and compare every output field.
- Stop at the first mismatch and name the input and the field that differs,
  with both values. Later mismatches may be consequences of the first.
- Find the cause before the fix: diff the two executions step by step
  (traces, intermediate state) and read the reference's code to know where to
  look. A small fixed difference (a constant charge, one extra read) usually
  has one cause.
- Fix with a test that fails before and passes after; store the failing
  input as a fixture when it is small.

## Survey mode

- Replay alone shows one bug per run. A survey run patches the
  implementation's state from the reference after each mismatch and carries
  on, so one run lists every mismatching input in a range and one bug becomes
  a work list.
- A patched run never counts as a pass. Mark its output (a flag file, a
  refused start) so patched state cannot leak into a result.

## Deliberate deviations

When the implementation is meant to differ from the reference, record it in
one deviations file: numbered, never renumbered, each with the reason. The
replay skips exactly those cases and no others.

## In practice

gakonst/goempo's `docs/HOW-IT-WAS-BUILT.md` (sections "How every claim was
verified" and "What mainnet replay found") shows the method on a node: full
mainnet replay comparing header commitments, a healing survey, an RPC
corpus, and a table of differences that unit tests and specs had passed:
https://github.com/gakonst/goempo/blob/1e6bc8be2d4563e5fb9f62d864d6fc1d85dad794/docs/HOW-IT-WAS-BUILT.md
