---
name: cloudformation
description: CloudFormation practice for templates, change sets and stacks that hold live infrastructure. Use for any change in a repo of CloudFormation templates, even a small one and even when the request never says CloudFormation, such as a security group rule, subnet, route, peering, IAM or instance change, a new stack, adopting existing AWS resources, reading a change set, or a failed or drifted stack. Covers how each property updates (in place, interruption, replacement), fixed names and Retain policies, why a rule is changed in two change sets, import and moves between stacks (import change sets, stack refactoring, the twin pattern), cross-stack contracts (SSM parameters against Exports), what `deploy` keeps between runs, stack-level tags, quotas, the validation ladder (cfn-lint, cfn-guard, pre-deployment validation), failure triage with describe-events, rollback recovery, drift, and the EC2 and VPC properties that replace a resource or drop traffic.
---

# CloudFormation

Practice for plain CloudFormation (YAML templates, JSON parameter files, the
AWS CLI). Commands, flags and quotas are in
`references/change-sets-and-deploys.md`; adoption, moves between stacks and
renames in `references/import-and-refactor.md`; linters, Guard rules and
service-side validation in `references/validation-and-policy.md`; failed and
stuck stacks and drift in `references/failures-and-drift.md`; the EC2 and VPC
properties that bite in `references/ec2-and-vpc.md`. The tool-independent
reasoning (stack boundaries, two-step changes, adoption against rebuild) is
in the `infrastructure-as-code` skill.

## House facts

- The desk's AWS infrastructure is CloudFormation, in the `infra/` repos
  under `~/dev`: one template per kind of stack, deployed once per
  environment and region, each with its own parameter file. The repo's
  `AGENTS.md`, or its `CLAUDE.md`, is the source of truth for naming, tags, the address plan,
  the stack layout, what counts as production and which validators run.
  Read it before proposing anything. This skill supplies the mechanics; the
  repo supplies the rules, and the repo wins.
- Where AWS's own `aws-cloudformation` skill is also loaded, the repo and
  this skill win on naming, cross-stack references, secrets and template
  metadata: add no attribution marker and no context metadata to a template
  unless the repo asks for them.
- Production changes go through a change set that a person reviews and
  executes. Preparing one is the job; executing one is not.

## What a change will do

- Every property of every resource type has an update behaviour, printed
  on its reference page as **Update requires**: *No interruption*, *Some
  interruptions*, or *Replacement*. Look it up for each property a change
  touches, including the ones that look harmless (a rule's CIDR, a
  description, a tag), and state each one's behaviour in the reply, one
  line per property. The resource schema lists the immutable ones
  (`createOnlyProperties`) and is a quick second check; the commands are in
  `references/change-sets-and-deploys.md`.
- **Replacement** creates a new physical resource, repoints references,
  and deletes the original during cleanup, usually in that order. The new
  resource has a new ID, a new address and, for stateful types, no data.
- A resource with a fixed physical name cannot be replaced: CloudFormation
  refuses an update that would do it. Changing an immutable property on
  such a resource means a new name, or a twin beside it
  (`references/import-and-refactor.md`).
- **The logical ID is the identity.** Renaming a logical ID is a delete of
  the old resource and a create of a new one. So is moving a resource to
  another template.
- Removing a resource from a template deletes it, unless its
  `DeletionPolicy` is `Retain`, in which case it lives on unmanaged.
- A `Condition` that turns false deletes every resource and output that
  carries it. Find them all before changing one.
- A changed parameter value is a changed property wherever it is
  referenced, with the same update behaviour.
- A value CloudFormation resolves at deploy time (an SSM parameter type, a
  dynamic reference without a version) can change a resource in a deploy
  whose template did not change.
- **A firewall rule, route or other access path is changed in two change
  sets, even when one quick change is asked for.** The first adds the new
  rules beside the old one, as new resources, and leaves the old rule's
  resource untouched. The second, later and separate, removes the old rule
  once the flow logs show nothing else used it. Write step one only, and
  say in the reply that step two follows. Editing a rule in place replaces
  it: CloudFormation removes the old rule, then adds the new one, and for a
  moment neither exists. Adding and removing in one change set avoids that
  gap but cuts off every other client of the old rule with no evidence
  that there are none.

## Reading a change set

- Create it, wait for it, then describe it with property values
  (`--include-property-values`). Without them a change set says that a
  property changes but not from what to what.
- For each resource read `Action` (`Add`, `Modify`, `Remove`, `Import`,
  `Dynamic`), `Replacement` (`True`, `False`, `Conditional`) and, per
  detail, `RequiresRecreation` (`Never`, `Conditionally`, `Always`) with
  the property name and what caused it.
- `Conditional` means CloudFormation cannot tell until it runs, usually
  because the new value depends on another resource that is itself
  changing. Treat it as a replacement until shown otherwise.
- Account for every `Remove` and every replacement, compare the number of
  changed resources with the intent, and treat any change the diff does not
  explain as a finding: a parameter that kept an old value, a re-resolved
  reference, a stack-level tag.
- A change set that fails with "didn't contain changes" is the answer "the
  stack already matches", not an error.
- Creating a change set provisions nothing. For a stack that does not
  exist yet it leaves an empty stack in `REVIEW_IN_PROGRESS`.
- Name a change set for the commit it was built from and put the full
  commit in its description, where the repo asks for that.

## Protect what must survive

- `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` together, on
  everything that holds data or a stable address: volumes, databases,
  buckets, log groups, Elastic IPs, VPCs and subnets. The first covers
  removal and stack deletion, the second covers replacement; one without
  the other leaves a hole.
- A retained resource that leaves a stack is not deleted. It is orphaned:
  running, unmanaged, and its fixed name still taken.
- Termination protection on every production stack, set when the stack is
  created and never lifted as part of a routine change.
- A stack policy can deny updates to named resources. It applies only
  during stack updates, and once set it can be replaced but not removed.
- Policy as code checks that the retain policies are there; a template
  that forgets one should fail the build, not the review.

## Adopting existing resources

- An import brings a live resource into a stack without recreating it. The
  template states its current properties exactly, each imported resource
  carries a `DeletionPolicy`, and the import changes nothing.
- CloudFormation does not compare the template with the live resource at
  import. A property stated wrongly is accepted and surfaces later as
  drift or as a surprise in the next update. Read the properties from the
  account the same day, and detect drift straight after the import.
- An import operation holds imports only. Anything new (an SSM parameter
  that publishes the resource's ID, a flow log) arrives in a second,
  ordinary update. Templates that serve both stages switch on a parameter.
- Renames and other changes to an adopted resource come after the import,
  as their own reviewed change sets.
- Some types can be imported but are not covered by drift detection
  (standalone security group rules, route table associations, gateway
  attachments). Compare those with the account by hand.
- Method, identifiers, limits and the stack refactoring alternative are in
  `references/import-and-refactor.md`.

## Stacks and the contracts between them

- A resource never changes stack for free. Choose its stack when it is
  created: by lifecycle and blast radius, one template deployed per
  environment and region.
- Stacks share values through SSM Parameter Store or through Exports.
  An Export cannot change or go away while any stack imports it, which
  locks the producer. An SSM parameter does not lock: the producer can be
  rebuilt and consumers pick up the new value on their next deploy, and
  nothing stops a producer being deleted under its consumers. With SSM,
  deploy and tear-down order is the discipline.
- A consumer reads an SSM value through a parameter of an SSM type
  (`AWS::SSM::Parameter::Value<AWS::EC2::VPC::Id>`) whose default is the
  path, overridden from the parameter file. The producer writes it with an
  `AWS::SSM::Parameter` in the template that creates the resource.
- SSM parameters cannot be read across regions. A value that must cross a
  region travels in a parameter file.
- Every route, rule and attachment has one owning stack. A stack never
  adds a route for a destination another stack owns.
- Publish an ID for anything another stack might need. An unread parameter
  is cheap; adding one later costs a producer deploy first.

## Parameters, tags and `deploy`

- Templates carry no environment or region specifics. Those live in one
  parameter file per stack, environment and region.
- `aws cloudformation deploy` keeps a parameter's previous value when the
  new invocation leaves it out. Removing a line from a parameter file does
  not clear it: set it to `""` and keep the line, so the file shows what is
  deployed. `create-change-set` and `update-stack` do the opposite: a
  parameter left out falls back to the template's default. Pass the whole
  file to either.
- Constrain what a parameter file can do: `AllowedValues` for enumerations,
  `AllowedPattern` for anything a policy rule would otherwise need to read
  (a CIDR whose mask may not be shorter than `/16`). Guard cannot see a
  value that arrives through a parameter.
- `NoEcho` hides a parameter from describe calls and nothing more. Secrets
  are dynamic references to Secrets Manager, never parameters.
- Stack-level tags are passed in full on every deploy and propagate to
  every taggable resource, so they are not repeated in templates, and none
  of their values may change from deploy to deploy: a commit or a date in a
  stack tag turns every deploy into an update of every resource.
- `AWS::Region` is the full code. Derive shorthands and per-region values
  from a `Mappings` block keyed on it.
- Templates passed inline must stay under 51,200 bytes. Measure with
  `wc -c` when a template grows; past the limit it needs an S3 bucket.

## Before it deploys

1. Run every validator the repo lists, in its order: the linter, the
   repo's Guard rules, the security scanner, the repo's own checks.
2. Fix findings. A suppression goes on one resource, with its reason, and
   only for what the repo lets be suppressed.
3. Create the change set. That runs the service's pre-deployment
   validation too; read its results with `describe-events`.
4. Read the change set as above and report it.
5. Stop. A person executes it.

After it runs: read the result back (the stack's status, the resources'
live properties, a real connection where a rule changed), and update the
documents the repo keeps in step.

## When it fails

- Fetch only the failures: `aws cloudformation describe-events
  --stack-name <stack> --filters FailedEvents=true`. Not
  `describe-stack-events`, which cannot filter and does not carry
  validation results.
- Read every failed event. A specific service error is a real failure;
  "Resource creation cancelled" is fallout from the rollback and says
  nothing about that resource. Several real failures can be parallel
  symptoms of one cause (a role missing several permissions): list them
  all.
- Say whether the fix is in the template or in the account (permissions,
  quota, a resource in the way). Never propose a template change for an
  account problem.
- `continue-update-rollback` with skipped resources, deleting a stack with
  retained resources, and disabling rollback all leave the stack's record
  disagreeing with reality. They are a person's decision, made knowing
  that; `references/failures-and-drift.md` has the states and the costs.

## Drift

- Detect it after every import, on a schedule, and before changing a stack
  that people can reach by console. Detection covers only supported types
  and only properties the template sets.
- An ordinary update does not put a drifted property back unless the
  update changes that property. A drift-aware change set
  (`--deployment-mode REVERT_DRIFT`) compares with the live resource and
  does.
- Settle each finding: revert the resource, or write the live value into
  the template.

## Gotchas

1. A logical ID renamed for tidiness: a delete and a create.
2. An immutable property changed on a resource with a fixed name: the
   update is refused, or worse, the resource had no fixed name and is
   replaced.
3. An import change set that also adds or changes something.
4. `DeletionPolicy: Retain` without `UpdateReplacePolicy: Retain`.
5. A line deleted from a parameter file to clear a value that `deploy`
   then keeps.
6. A value moved between two parameters in one deploy, colliding with
   itself (a duplicate security group rule).
7. A changing value in a stack-level tag.
8. A long-lived instance whose image, key pair or launch template version
   follows "latest".
9. A firewall rule replaced in one deploy instead of added, verified, then
   removed.
10. A template past 51,200 bytes because old and new resources coexist
    during a migration.
11. `describe-stack-events` used to look for validation errors.
12. A Guard rule that reads a literal and misses the `!Sub` form, or reads
    inline rules and misses standalone ones.
13. An Export added because it was convenient, now locking its stack.
14. Trusting `IN_SYNC` for a property the template never set.
