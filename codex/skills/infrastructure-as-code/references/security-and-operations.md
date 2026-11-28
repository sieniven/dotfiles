# Secrets, identity, supply chain and day-2 operations

## Secrets

- A secret never appears in a template, a parameter file, a tfvars file, a
  CI variable echoed to a log, or a tag. It lives in a secret manager and
  the code holds its name.
- Resolution happens as late as possible: at deploy time by reference, or
  better at run time by the workload's own identity, so the deploying tool
  never sees the value.
- Know what your tool stores. Terraform and OpenTofu keep resolved values in
  state in clear text, and marking a value sensitive only hides it from
  output; write-only arguments and ephemeral values keep it out, and
  OpenTofu can encrypt state. Pulumi encrypts each secret value in its
  state. CloudFormation resolves secret-manager references at deploy time
  and does not echo them, but a secret passed as an ordinary parameter is
  visible to anyone who can describe the stack.
- A secret that reached a log, a plan artifact or git history is rotated,
  not deleted.
- One secret per consumer where the store grants access per secret: a
  shared bundle hands every reader everything in it.

## Identity

- **People** sign in through single sign-on to roles, assigned by group.
  Production access is read-only by default; changes go through the
  pipeline. Break-glass access exists, is logged, and is reviewed after use.
- **Pipelines** assume a role through the CI system's OIDC identity, with
  no stored access key. The role's trust policy names the repository and
  the branch or environment allowed to assume it. Planning uses a read-only
  role; applying uses a separate one, reachable only from the protected
  branch or an approved environment.
- **Workloads** use the platform's attached identity (instance role, task
  role, workload identity), scoped to what that role does, with conditions
  that pin where it may be used from (its network, its own address). No
  long-lived keys on a machine.
- **Vendors** get their own role sized from what they demonstrably do (the
  audit log shows it), written as explicit actions rather than a managed
  policy the provider can widen without review.
- Least privilege for the deployer is hard, because it creates IAM. Bound it
  with permission boundaries or organisation policies, and review any
  change to those like a production change.

## Network exposure

- Default deny. Every rule names who it is for, and has a description.
- Reference identities (security groups, service accounts) inside a
  network; use address ranges only where an identity cannot be referenced
  (another region, another provider, the internet).
- No catch-all "the whole private range" rule: it admits every network ever
  peered or tunnelled in, including people on a VPN.
- Open-to-the-internet ingress is allowed only where a naming or tagging
  rule marks the group as public, so policy can check it.
- Record traffic (flow logs) before narrowing rules: the log shows who
  really connects, and after the change shows who was refused by mistake.

## Supply chain

- Pin the tool, its providers and modules, and commit lock files. Upgrade
  in a change of its own.
- Pin third-party CI actions to a full commit, not a tag that can move.
- Pin machine images by ID for long-lived hosts (a moving "latest" replaces
  the host whenever the vendor publishes); resolve the latest image only
  for hosts that are meant to be replaced.
- SLSA's build levels name how far a build can be trusted: L1 has
  provenance, L2 a hosted build platform that signs it, L3 a hardened one.
  Aim for provenance on anything that ends up running in production.
- Policy scanners are part of the chain too: run them from pinned versions,
  and prefer rules kept in the repo over a remote rule set that changes
  under you.

## Policy as code tools

| Tool | Evaluates |
|------|-----------|
| cfn-lint | CloudFormation templates against the resource schemas and best-practice rules |
| cfn-guard | CloudFormation (and any JSON or YAML) against rules written in Guard |
| OPA with Conftest | Any structured input, a Terraform plan in JSON included, against Rego |
| Sentinel | Terraform plans inside HCP Terraform and Terraform Enterprise |
| Checkov, Trivy, KICS | Many IaC formats against built-in security rule sets |
| Cloud-side hooks and organisation policies | The change itself, at the provider, whatever tool made it |

Local rules give the fastest feedback and encode house conventions;
provider-side controls are the ones that cannot be skipped.

## Day 2

- **Observability baseline** on every host or service from the template
  that creates it: metrics, logs with a retention period, a health signal,
  and an alert routed to someone.
- **Backups** are a schedule plus a tested restore. A retained disk guards
  against a replaced instance, not against a deleted file or a bad write.
- **Patching** has an owner per host class: rebuilt from a new image, or
  patched in place by a named person.
- **Capacity and cost**: tag for ownership, alert on idle spend, and state
  the purchasing mode (on-demand, burstable credit behaviour) where it can
  surprise.
- **Runbooks** live beside the code, are written for the person on call at a
  bad hour, and start with how to tell whether this runbook applies.
- **Documentation of the estate** (diagrams, inventories of what is not yet
  managed) is generated or regenerated by commands recorded in the
  document, and updated in the pull request that changes the estate.

## Incidents

1. Stop the harm first: the smallest reversible action that does it.
2. If that action was a hand edit to managed infrastructure, record it at
   once (what, where, when) and write it into code the same day, or revert
   it.
3. One person decides; changes are announced before they are made.
4. Afterwards, a blameless review: timeline, what made it possible, what
   made it slow to notice, and the changes that follow. A recurring class of
   mistake becomes a policy rule or a pipeline check, not a reminder.
