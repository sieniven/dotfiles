# The change pipeline, rollout and rollback

How a change to infrastructure travels from a commit to production, and how
it is taken back. Tool commands are in `tool-map.md`.

## Stages

1. **Static checks** on every push: formatter, linter, schema validation.
   Seconds, no credentials, no cloud calls.
2. **Policy as code**: the repo's conventions and the security floor as
   rules that fail the build. Naming, mandatory tags, retain on stateful
   resources, no open ingress outside the groups meant to be public,
   encryption, a description on every firewall rule. A rule and the
   document it enforces change in the same pull request.
3. **Plan**, with read-only credentials: the tool's own statement of what it
   will create, change, replace and delete. Attached to the pull request.
4. **Review** of code and plan together. The reviewer answers: is every
   replace and delete intended; does the count match the intent; is anything
   here that the diff does not explain.
5. **Apply** of exactly that plan, with the applying role, after merge or
   approval. Lower environments automatically; production behind a person.
6. **Verify**: read the result back and prove it works from outside.
7. **Record**: the plan name or description carries the commit; the tool's
   event history and the cloud audit log carry the rest. Do not write deploy
   history into resource tags.

A plan goes stale: if the record or reality changed between plan and apply,
a good tool refuses the saved plan. Plan again and review again; do not
force it.

## What each test level is for

| Level | Catches | Cost |
|-------|---------|------|
| Format, lint, schema | Typos, wrong property names and types | Free, seconds |
| Policy | Convention and security violations | Free, seconds |
| Plan review | Wrong action on a real resource: replace, delete, scope | Read-only cloud calls |
| Plan assertions, native tests | Module logic: counts, names, conditionals | Free with mocks |
| Ephemeral integration | That it really deploys and connects | Real resources, minutes, money |
| Post-apply verification | That production works now | Part of every apply |

Spend where the bugs are. For a network or a firewall the plan and the
policy rules catch nearly everything; an ephemeral copy proves little about
the one that carries traffic. For a module reused by many stacks, native
tests and an example deployment pay for themselves.

## Environments and promotion

- Build once, promote the same commit. A change that reaches production
  through a different code path than it was tested on was not tested.
- Per-environment parameter files hold every difference. A value missing
  from a file should fail, not silently default to another environment's.
- Know your tool's rule for a parameter left out of a later deploy: some
  keep the previous value, so deleting a line does not clear it. State
  "empty" explicitly and keep the line.
- Production-only resources exist (the adopted network, the one real
  peering). Their only pre-production test is the plan: say so in the pull
  request, and review accordingly.

## Changing things safely

**Expand and contract** (also: parallel change, make-before-break). For
anything a client depends on:

1. Add the new form beside the old (the new rule, record, credential, name).
2. Apply. Both work.
3. Move the clients, or wait for them to move.
4. Prove the old form is unused, from evidence: flow logs, access logs,
   query logs, connection counts. A week of real traffic beats an argument.
5. Remove the old form in a second change.

It applies to firewall rules narrowed from a range to named sources, to a
group or resource that must be renamed, to DNS records, to credential
rotation, to a port moving, to a schema change under a running service.

**Replacing something with an immutable property** (a name, an encryption
setting, a subnet's zone) is the same pattern: create the twin, attach or
route to both, detach the old, delete it. Each step is its own reviewed
change.

**One concern per change.** A refactor that should produce an empty plan is
applied alone, so an empty plan proves it. A tool or provider upgrade is
alone, so a new diff is attributable. A behaviour change is alone, so its
rollback is clean.

**Sequencing across stacks.** A producer gains the new output first;
consumers move to it; the producer drops the old output last. Tear-down runs
in the reverse of deploy order.

## Rolling out compute

| Strategy | How | Rollback | Costs |
|----------|-----|----------|-------|
| In place | Change the running hosts | Change them back | Downtime risk; drift between hosts |
| Rolling | Replace a few at a time behind a balancer | Roll the other way | Two versions live at once |
| Blue-green | Stand up a full new set, switch traffic | Switch back | Double capacity during the switch |
| Canary | Send a small share to the new version, watch, widen | Send it back | Needs traffic splitting and metrics that decide |
| Immutable replace | New image, new instances, retire old | Launch the previous image | Slow for stateful hosts |

- A deploy needs a health check that fails when the service is broken, not
  when the process merely exists: it exercises a dependency, not a constant
  `200`.
- Data changes ride ahead of code: a schema change is backward compatible
  with the previous release for at least one cycle, so rolling the code back
  does not strand it.
- A host that cannot be replaced freely (stateful, allowlisted address,
  hand-customised) is changed in place by a written, reversible procedure,
  one host first.

## Rollback

- Decide before applying what "undo" is for this change, and write it in the
  pull request: the command, how long it takes, and what it will not
  restore.
- Reverting the commit and applying is a new change with a new plan. Read
  that plan too.
- The tool's automatic rollback puts configuration back. It does not bring
  back deleted data, a replaced resource's identity, or a released address.
- Some failures leave the tool itself stuck (a rollback that fails, a lock
  held). Diagnose from its event log; the "skip this resource" and "force
  unlock" switches leave the record disagreeing with reality and are a
  person's decision.
- Roll forward when the fix is small and understood; roll back when it is
  not. Either way stop the harm first, explain afterwards.

## Measuring delivery

The DORA measures describe a delivery process from outside. Throughput:
*change lead time* (commit to running in production), *deployment
frequency* and *failed deployment recovery time*. Instability: *change fail
rate* and *deployment rework rate* (unplanned deployments made to fix an
incident). They move together in healthy teams: small, frequent, reviewed
changes fail less and recover faster. Use them to see a trend, never as a
target for a person.
