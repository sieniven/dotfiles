# The same concepts in each tool

Checked against each project's documentation on 2026-11-28 (Terraform
1.17, OpenTofu 1.13, the CDK v2 CLI, current Pulumi). Versions in brackets
are where a feature arrived; check the version in use before relying on
one. CloudFormation's own mechanics are in the `cloudformation` skill.

## Concept map

| Concept | CloudFormation | CDK | Terraform, OpenTofu | Pulumi |
|---------|----------------|-----|---------------------|--------|
| Unit of deployment | Stack | Stack, synthesized to a template | Root module with its state | Stack |
| The record | The stack, held by the service | Same | State file in a backend, with a lock | Checkpoint, in Pulumi Cloud or your backend |
| Identity | Logical ID | Logical ID derived from the construct path plus a hash | Resource address | URN |
| Plan | Change set | `cdk diff`; `cdk deploy --method=prepare-change-set` | `plan -out=FILE` | `preview` |
| Apply the reviewed plan | `execute-change-set` | Execute the prepared change set | `apply FILE` | `up` plans again; saved plans (`preview --save-plan`, `up --plan`) are not GA |
| Rename without replacing | Stack refactoring | `cdk refactor` (preview), `overrideLogicalId` | `moved` block (1.1) | `aliases` |
| Adopt an existing resource | Import change set | `cdk import` | `import` block (1.5); `plan -generate-config-out` (experimental) | `import` option, `pulumi import` |
| Let go without destroying | `DeletionPolicy: Retain`, then remove | `RemovalPolicy.RETAIN`; `cdk orphan` | `removed` block (1.7), with `destroy = false` | `retainOnDelete` |
| Refuse to destroy | Retain policies, termination protection, stack policy | `RemovalPolicy` | `prevent_destroy` | `protect` |
| Replacement order | Usually new first, old deleted in cleanup | Same | Old first by default; `create_before_destroy` | New first by default; `deleteBeforeReplace` |
| Declare a field ignored | Not available per property | Not available | `ignore_changes` | `ignoreChanges` |
| Detect drift | Drift detection | `cdk drift` | `plan -refresh-only`, `-detailed-exitcode` | `refresh --preview-only` |
| Revert drift | Drift-aware change set | `cdk deploy --revert-drift` | A normal `apply` | A normal `up` after `refresh` |
| Move between stacks | Stack refactoring; or retain, remove, import | `cdk refactor` (preview) | `moved` within a state; `removed` plus `import` across states | `pulumi state move` |
| Contract between stacks | Exports (hard), SSM parameters (soft) | Same; cross-stack references become exports | Remote state or data sources | Stack references |
| Secrets in the record | Resolved at deploy by dynamic reference | Same | In state in clear; ephemeral values (1.10) and write-only arguments (1.11; OpenTofu 1.11) keep them out; OpenTofu encrypts state (1.7) | Encrypted per value |
| Policy as code | cfn-guard, Hooks | cfn-guard on the synthesized template | OPA/Conftest on the plan JSON, Sentinel, Checkov, Trivy | Pulumi policy packs |
| Tests | Rule tests, change-set review | Assertions on the synthesized template | `terraform test` (1.6), mock providers (1.7; OpenTofu 1.8), `check` blocks (1.5) | Unit tests of the program |

## Notes that change decisions

**Saved plans.**
- Terraform applies a saved plan without re-planning and refuses it when
  the state has moved on since ("Saved plan is stale"). It checks the state
  only: drift in the real resources since the plan is not noticed.
- A saved plan file can hold sensitive values in clear. Treat it like state.
- Pulumi's `up` computes its own plan; constraining it to a saved one is
  still marked experimental. The review there is of `preview` output from
  the same commit, with no changes in between.
- CDK's default deploy creates and executes a change set in one go. To put a
  person between the two, prepare the change set and execute it separately.

**Identity.**
- CDK logical IDs come from the construct path: renaming a construct ID or
  moving a construct under another parent changes the logical ID and
  replaces the resource. A construct named `Default` is left out of the
  path, which is how a resource is wrapped without changing its ID.
- Terraform's `count` keys resources by position: removing a middle element
  shifts every later address. Use `for_each` with stable keys for anything
  that must keep its identity.
- `prevent_destroy` rejects a plan that destroys the resource, but not when
  the resource block itself is deleted from the code. It is a guard against
  a bad change, not against a removed file.

**Replacement order.**
- CloudFormation usually creates the replacement before deleting the
  original, and refuses outright to replace a resource that has a fixed
  physical name.
- Terraform destroys first unless `create_before_destroy` is set, which
  means a gap unless it is set; with it, the same fixed-name problem
  appears.

**Rules as their own resources.**
- A firewall rule declared as a separate resource has its own identity, so
  the expand step is a pure add and the contract step a pure remove. A rule
  declared inline on its group is changed by rewriting the group's list,
  and the provider decides what is revoked in between. Where rules change
  over time, declare them separately (Terraform's
  `aws_vpc_security_group_ingress_rule`, CloudFormation's
  `AWS::EC2::SecurityGroupIngress`).

**Fast paths that are for development only.**
- `cdk deploy --hotswap` changes resources directly and deliberately
  introduces drift. `--revert-drift` puts the stack back.
- CloudFormation's Express mode returns as soon as configuration is applied,
  before resources are ready, with rollback off by default.

**Locking.**
- Terraform's S3 backend locks with `use_lockfile` (1.10, GA in 1.11);
  DynamoDB locking is deprecated there. OpenTofu supports both and has not
  deprecated either.

**Larger structures.**
- Terraform Stacks (HCP Terraform) and CloudFormation StackSets deploy one
  definition to many accounts or regions. Reach for them when the same
  stack really is repeated, not to tie different stacks together.
- Terraform's `terraform query` with list resources (1.14) and
  CloudFormation's IaC generator find unmanaged resources and draft the
  code to import them. The draft is a starting point; read every property
  against the live resource before importing.

**Continuous controllers.**
- Crossplane's managed resources treat the manifest as the source of truth
  and revert outside changes; a management policy can restrict one to
  observing.
- AWS Controllers for Kubernetes reconcile spec changes at once and catch
  drift on a periodic resync measured in hours, not seconds.
- CloudFormation Git sync makes a stack follow a branch: a commit to the
  template or its deployment file updates the stack with no reviewed change
  set in between. Fit for development stacks; decide deliberately for
  anything else.

## Choosing

- **Stay with what the estate uses.** A second tool means two records, two
  pipelines and resources whose owner is unclear. Migrating is an adoption
  project: import, empty plan, then change.
- **CloudFormation** where the estate is AWS only, the record should be
  held by the provider, and the people reviewing want the template to be
  the thing deployed. Its limits: no per-property ignore, weak modularity,
  one account and region per stack.
- **CDK** where the same AWS shapes repeat and a typed program earns its
  keep. Review the synthesized diff, and watch identity when refactoring.
- **Terraform or OpenTofu** where more than one provider is in play
  (cloud, DNS, SaaS, GitHub), or the team wants explicit state surgery and
  a large module ecosystem. The state file is yours to protect.
- **Pulumi** where the team wants general-purpose languages across
  providers and per-value secret encryption.
- **A controller** (Crossplane, ACK) where a Kubernetes platform team
  already runs the cluster as the control plane and wants drift reverted
  continuously.

## Sources

- Terraform: <https://developer.hashicorp.com/terraform/language>, CLI
  `plan` and `apply` pages, and the release changelogs.
- OpenTofu: <https://opentofu.org/docs/>
- Pulumi: <https://www.pulumi.com/docs/iac/concepts/options/>,
  <https://www.pulumi.com/docs/iac/concepts/secrets/>
- CDK: <https://docs.aws.amazon.com/cdk/v2/guide/>
- Crossplane: <https://docs.crossplane.io/>; ACK:
  <https://docs.aws.amazon.com/eks/latest/userguide/ack-concepts.html>
- The failure-mode framing in `../SKILL.md` follows Anton Babenko's
  `terraform-skill` (<https://github.com/antonbabenko/terraform-skill>,
  Apache-2.0), and the refactor-without-replace emphasis follows Pulumi's
  agent skills (<https://github.com/pulumi/agent-skills>, Apache-2.0).
