---
name: infrastructure-as-code
description: Infrastructure-as-code and DevOps delivery practice, independent of tool. The paradigms (declarative desired state, idempotence and convergence, one-shot versus continuous reconciliation, immutable versus mutable infrastructure), resource identity and what replaces a resource, how to cut stacks by lifecycle and blast radius and join them through one-way contracts, environments and promotion, adopting hand-built infrastructure versus rebuilding it, drift, names, tags and address plans as interfaces, the change pipeline (static checks, policy as code, a reviewed plan tied to a commit, apply, verify), two-step changes and rollback, secrets, deployer identity and supply-chain pinning, and day-2 operations. Carries a concept map across CloudFormation, CDK, Terraform, OpenTofu and Pulumi. Use when designing or reviewing infrastructure code, a stack layout, a deployment pipeline, a migration or an adoption plan, or when choosing between IaC tools or approaches.
---

# Infrastructure as code

Practice for infrastructure that is defined in files, reviewed as diffs and
changed through a pipeline, whatever the tool. The vocabulary and the
paradigms behind it are in `references/paradigms.md`; the change pipeline,
rollout and rollback patterns in `references/delivery.md`; secrets, deployer
identity, supply chain and day-2 work in
`references/security-and-operations.md`; the same concepts in CloudFormation,
CDK, Terraform, OpenTofu and Pulumi in `references/tool-map.md`. For
CloudFormation itself use the `cloudformation` skill.

A repo's own conventions (its CLAUDE.md, naming and tag rules, stack layout,
what counts as production) win over anything here. Read them first.

## Ground rules

- The code is the only way a managed resource changes. A console or CLI edit
  to a managed resource is drift: found late, and reverted by the next apply.
  A break-glass edit in an incident is written back into code the same day.
- Every change is read twice: the code diff, and the tool's plan of what it
  will do to real resources (change set, plan, preview). The second is the
  one that matters; a one-line diff can replace a database.
- What is applied is the plan that was reviewed, built from a named commit,
  not a fresh plan computed at apply time.
- An agent prepares the plan for production and stops. Applying it, deleting
  a stack, forcing a rollback or lifting a protection is a person's action.
- Nothing sensitive in code, parameter files or plan output.

## The model

- **Declarative.** Files state what exists; the tool works out the actions.
  Imperative steps (scripts, provisioners, custom resources, boot scripts)
  are the escape hatch and carry none of the guarantees: each one is made
  idempotent and says what undoes it.
- **Idempotent and convergent.** Applying twice changes nothing the second
  time, and an empty plan is the test. A plan that is never empty hides the
  real change in noise: fix the cause (normalise the value, declare the
  server-set field ignored), never learn to skim past it.
- **Three states.** The code (desired), the tool's record (state file, stack)
  and reality. A plan compares code with the record and, where the tool
  refreshes, with reality. Drift is reality that left the record; unmanaged
  is reality no record ever held.
- **One-shot or continuous.** CloudFormation, Terraform and Pulumi act when
  run and notice drift only when asked. Controllers (Crossplane, Argo CD,
  Flux) reconcile continuously and can revert a hand edit on their next
  pass. Know which one holds a resource before editing it by hand in an
  incident.

## Identity and replacement

- Every resource has an identity in the tool (logical ID, address, URN) bound
  to a physical one. Renaming it in code, moving it between modules or
  stacks, or changing a loop key is, by default, delete and create. Use the
  tool's move mechanism (`references/tool-map.md`) and confirm the plan shows
  no delete.
- Every property is one of: changed in place, changed with an interruption,
  or immutable (changing it replaces the resource). Look it up before
  proposing the change, then find the replacement marker in the plan.
- Replacement creates the new resource first only if two can coexist. A fixed
  physical name forces delete-first or fails outright, so names are generated
  unless the name is itself an interface, and then it is immutable for life.
- Classify every resource before touching it:
  - **stateful**: holds data (databases, volumes, buckets, log groups);
  - **addressable**: others depend on its address or ID (public IPs, DNS
    names, networks, subnets, firewall group IDs, keys);
  - **disposable**: everything else.
  Stateful and addressable resources are protected from delete and replace
  (retain policies, prevent-destroy, deletion and termination protection), so
  a bad diff fails loudly rather than destroys quietly.
- Changing something immutable on a live resource is three steps, never one:
  build a twin beside it, move the consumers, remove the original.

## Boundaries and contracts

- A stack (state, project) is the unit of blast radius, locking, review and
  rollback. Cut by lifecycle and rate of change, by owner and by blast
  radius: network and identity (slow, shared, catastrophic) apart from
  compute (fast); data stores apart from the services that use them; one
  instance per environment and region.
- What changes together and fails together lives together. Too large, and
  every change locks everything and the plan cannot be read; too small, and
  ordering between stacks becomes the work.
- Dependencies point one way (foundation, then platform, then workload) with
  no cycles. A lower layer never reads a higher one.
- Stacks meet through a published contract (outputs, a parameter store,
  remote state), never by looking each other's resources up by name or tag.
  A hard link (a CloudFormation Export) locks the producer while anything
  consumes it; a parameter-store value does not, and then nothing stops the
  producer vanishing under its consumers: deploy order is the discipline.
- Every resource, and every route, rule and attachment, has exactly one
  owning stack. Two owners fight on every apply.
- Moving a resource between stacks later is real work. Pick the stack when
  the resource is created.
- A module, construct or component is a contract: a narrow typed interface,
  versioned and pinned. Abstract on the third use, not the first.

## Environments

- One body of code, one parameter file per environment and region.
  Differences live in those files, not in copies of the code or conditionals
  scattered through it; the few structural differences (one NAT or one per
  zone) are named conditions.
- Separate accounts isolate best. Sharing one account makes the environment
  segment of every name load-bearing and puts the whole burden on network
  rules and IAM conditions.
- The same commit is promoted from the lower environment to production.
  Where something exists only in production, the plan review is the only
  test: review it as one.
- Development may apply on merge. Production gates on a person.

## Changing live infrastructure

- Account for every replace and every delete in the plan, check the count
  against intent, and treat anything unrelated as a finding: it is drift or
  an unpinned dependency, and it gets its own change.
- **Two steps (expand, then contract)** for firewall rules, DNS, credentials,
  names and anything a client holds: add the new beside the old and apply;
  verify from evidence (flow logs, access logs, metrics), not from belief;
  remove the old in a second change.
- One kind of change per apply: no refactor with a behaviour change, no tool
  or provider upgrade with a functional change.
- Rollback is a forward change: the previous commit applied again, with its
  own plan. It restores configuration, never deleted data or a replaced
  resource. Know the one-way changes (deletes, replacements, data
  migrations, key rotations) and give them a backup and a longer look.
- After the apply, read back. The tool's "complete" means the API accepted
  the change; the check is that the thing works (a health check, a real
  connection from a real client, a refused connection where one is wanted).

## Adopting what already exists

- **Import** brings a live resource under code without recreating it;
  **rebuild** creates a new one from code and migrates to it. Adopt where
  replacement costs downtime, addresses or third-party allowlists; rebuild
  where the old shape is wrong and cheap to replace.
- Import exactly what exists, so the first plan after it is empty; bring it
  to the conventions afterwards, in reviewed steps. Never import and change
  in one operation.
- Read the live properties the same day, never from memory or an old
  diagram. Protect every adopted resource from deletion before anything
  else.
- Mark ownership on the resource (a managed-by tag) and keep an inventory of
  what is still unmanaged, regenerated by commands, shrinking with each
  adoption or retirement.

## Drift

- Detect on a schedule, not by accident. Each finding is settled one way:
  reverted to the code, or accepted into the code. None is left.
- Prevent it at the source: read-only console access in production, changes
  only through the pipeline's role.
- Drift that is designed (an autoscaler's count, a rotated password, tags
  another system writes) is declared ignored in code, per field.

## Conventions are interfaces

- Names, tags and address plans are read by people, IAM conditions, policy
  rules and cost reports. Write the convention once, enforce it with policy
  as code, and change rule and document in the same pull request.
- **Names**: fixed segment order, one character set, nothing that changes
  (no dates, no people), each segment meaning one thing in every name.
- **Tags**: a small mandatory set (environment, product or service,
  managed-by, stack), applied at stack level where the tool allows. No tag
  value changes from one apply to the next (no commit, no date): it would
  turn every apply into an update of every resource and bury the real one.
- **Addresses**: every network range allocated from one written plan, no
  overlaps across any environment or region, recorded before it is created
  and never reused. Overlap is free today and costs a renumbering the day
  two networks must talk.

## The change pipeline

| Stage | What it proves | Typical tools |
|-------|----------------|---------------|
| Format, lint | The code parses and follows the style | cfn-lint, `terraform fmt`/`validate`, tflint |
| Policy as code | Conventions and the security floor hold | cfn-guard, OPA/Conftest, Checkov, Trivy |
| Plan | What will happen to real resources | change set, `plan -out`, `preview` |
| Review | A person accepts that plan | pull request, environment approval |
| Apply | The reviewed plan, nothing else | execute change set, `apply <file>` |
| Verify | It works, and nothing else broke | read-backs, health checks, logs |
| Watch | It stays as applied | drift detection on a schedule |

- Effort goes where infrastructure bugs are caught: plan review and policy.
  Integration tests against real resources are slow and cost money; keep
  them for modules many stacks share.
- Policy findings are fixed. A suppression sits on one resource with its
  reason beside it, never in a global config.
- Every plan carries the commit it was built from, in its name or
  description, so an applied change traces back to the code.

## Secrets, identity, supply chain

- Secrets live in a secret manager and are referenced by name. Know whether
  the tool writes resolved values into its state, and who can read that.
- The deployer is the most privileged principal there is. CI assumes a role
  through OIDC, with no long-lived keys; the planning role is read-only; the
  production apply role is assumable only from the protected branch or
  environment.
- Pin what the pipeline runs: tool version, provider and module versions,
  third-party CI actions by commit, machine images for long-lived hosts.

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| A rename shows as delete and create | Identity changed | The tool's move mechanism; plan again |
| The plan is never empty | Unnormalised value, or a field the provider sets | Normalise it, or ignore that field explicitly |
| Unrelated resources in the plan | Drift, or an unpinned dependency | Settle the drift first; pin; separate change |
| The apply stopped half way | A late failure after early successes | Read the events for the first real error; fix forward or let the rollback finish; never hand-edit to "help" |
| Two applies undo each other | One resource, two owners | Give it one owner; the other reads it |
| The producer cannot be changed | A hard export is consumed | Move consumers to a soft contract, then change |
| Works in dev, fails in prod | A hard-coded value, a quota, a global name | Parameterise; check quotas; generate names |
| "Somebody fixed it in the console" | Drift | Revert it or write it into code, today |
| A secret in the plan log or state | Passed as a plain value | Reference the secret manager; rotate it |
| Delete fails, or deletes too much | No protection on stateful resources, or protection never tested | Retain policies and protections, checked by policy |

## Gotchas

1. Reviewing the code diff and not the plan.
2. Applying a plan computed after the review instead of the reviewed one.
3. A rename, a re-key or a move between stacks done as a text edit.
4. Import and change in the same operation.
5. A firewall rule or credential swapped in one step, with a gap in between.
6. A changing value in a stack-wide tag.
7. An overlapping network range, because the two networks would never meet.
8. A stateful resource with no retain policy, or a retain policy nobody has
   read back.
9. Environment differences coded as copies or scattered conditionals.
10. Trusting "apply complete" without checking the thing works.
11. A long-lived access key in CI, or a deployer role any branch can assume.
12. A suppression in a global config, or one without a reason.
