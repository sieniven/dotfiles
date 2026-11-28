# Paradigms and vocabulary

The ideas the rules in `../SKILL.md` rest on, with the words people use for
them. Sources are at the end.

## Declarative and imperative

- **Declarative**: the code describes the end state; the tool diffs it
  against what it knows and derives create, update and delete actions.
  CloudFormation, Terraform, OpenTofu, Kubernetes manifests.
- **Imperative**: the code is the sequence of actions. Shell scripts, most
  SDK scripts, classic configuration-management runs.
- **Declarative through a program**: CDK and Pulumi run general-purpose code
  whose output is a declarative graph (a synthesized template, a resource
  graph). The program is imperative; what is deployed is still desired
  state. Loops and conditionals decide what exists, so the thing to review
  is the synthesized diff, never the program alone.
- Where a declarative tool cannot express a step (run a migration, call an
  API with no resource type), the escape hatch is an imperative step inside
  it: a provisioner, a custom resource, a `local-exec`, a boot script. It
  runs once or on a trigger, the tool cannot plan its effect, and it is the
  first thing to break on a re-run. Keep such steps few, idempotent, with an
  undo, and never use one where a real resource type exists.

## Idempotence and convergence

- **Idempotent**: running the same apply again yields the same result and
  changes nothing.
- **Convergent**: from any starting point (fresh, half-applied, drifted) the
  apply moves reality toward the declared state.
- The practical test is the empty plan after an apply. Common reasons it is
  not empty: a value the provider normalises (case, ordering, a default it
  fills in), a field another system writes (an autoscaler, a rotation), a
  timestamp or random value regenerated on each run, an unpinned image or
  version lookup.

## State

Every tool keeps a record that binds an identity in code to a physical
resource, with the properties it last applied:

| Tool | Record | Held by |
|------|--------|---------|
| CloudFormation, CDK | The stack | The service, per account and region |
| Terraform, OpenTofu | The state file | A backend you choose (object store, HCP), with a lock |
| Pulumi | The stack's checkpoint | Pulumi Cloud or a self-managed backend |
| Crossplane, ACK | Custom resources | The cluster's API server |

What follows from it:

- The record is as sensitive as the infrastructure: it lists everything and
  may hold secrets in clear. Restrict who reads it; encrypt it; version it.
- It is a single point of serialisation: one writer at a time. A stuck lock
  or a stack stuck mid-operation blocks every change behind it.
- A service-held record (CloudFormation) cannot be edited, lost or
  hand-repaired: fewer disasters, fewer escape routes. A file-backed record
  can be surgically edited (`state mv`, `state rm`), which is both the
  remedy and the hazard.
- Losing the record does not delete the resources; it orphans them. Getting
  them back under code is an import.

## Mutable and immutable infrastructure

- **Mutable**: a server is built once and changed in place (patches,
  packages, config pushes). State accumulates; two servers built a year
  apart differ in ways nobody recorded (configuration drift, the
  "snowflake").
- **Immutable**: a server is never changed after launch. A change builds a
  new image, launches new instances and retires the old. Rollback is the
  previous image; drift has no time to accumulate.
- "Pets and cattle" names the same split by attitude: a pet is nursed back
  to health; one of the herd is replaced.
- Most estates hold both, and the honest thing is to say which is which.
  Stateless services belong on the immutable side. A database, a
  hand-customised workstation or a host whose address third parties have
  allowlisted is a pet by necessity: protect it (retained disk, pinned
  image, stable address), document that its contents are not the template's
  responsibility, and keep the template from replacing it by accident.
- Provisioning (create the resource) and configuration (make the machine
  right inside) are different jobs. An image baked ahead of time plus a
  thin boot script beats a long boot script; a boot script that runs once
  is not reapplied when the template changes unless the instance is
  replaced.

## One-shot and continuous reconciliation

- **One-shot (push)**: a pipeline or a person runs the tool; it reconciles
  once and exits. Drift persists until the next run or a drift check.
- **Continuous (pull)**: an agent inside the target watches the declared
  state and reality and corrects differences all the time. Kubernetes
  controllers work this way; Crossplane and ACK extend it to cloud
  resources; Argo CD and Flux apply it to what a cluster runs.
- **GitOps** is the continuous model with git as the declared state. The
  OpenGitOps principles: the desired state is *declarative*, *versioned and
  immutable*, *pulled automatically* by agents, and *continuously
  reconciled*.
- Push pipelines need credentials that reach into the target from outside;
  pull agents need only read access to the repository. Push gives an
  explicit, reviewable plan before each change; pull gives fast drift
  correction and, by default, no per-change plan to review. For network,
  identity and data stores the reviewed plan is usually worth more.

## DSL or general-purpose language

| | DSL (YAML/JSON templates, HCL) | Program (CDK, Pulumi) |
|---|---|---|
| Reads as | The resources themselves | Code that produces resources |
| Abstraction | Limited (modules, macros, loops) | Unlimited (functions, classes, packages) |
| Review | The diff is close to the change | Review the synthesized diff as well |
| Testing | Policy and plan checks | Those, plus unit tests of the program |
| Hazard | Repetition, copy-paste drift | Clever code hiding what gets deployed; identity changing when code is refactored |

Small, flat, slow-changing estates (a network, a few hosts) are well served
by a DSL: what is written is what exists. Large estates with repeated shapes
earn a program's abstractions. Mixing is normal; a migration between them is
an adoption project, not a rewrite of syntax.

## Everything as code

The same discipline applies to what surrounds the infrastructure: policy
rules, dashboards and alerts, pipeline definitions, runbooks, and the
diagrams and inventories that describe the estate. A document that states
what is deployed changes in the same pull request as the deployment.

## Sources

- Kief Morris, *Infrastructure as Code* (O'Reilly, 3rd edition): stacks,
  the patterns for cutting and connecting them, environments, pipelines.
- OpenGitOps principles, v1.0.0: <https://opengitops.dev/>
- HashiCorp, *Terraform recommended practices* and the Terraform language
  documentation: <https://developer.hashicorp.com/terraform>
- Pulumi concepts documentation: <https://www.pulumi.com/docs/iac/concepts/>
- AWS Well-Architected Framework, operational excellence pillar.
- Google, *Site Reliability Engineering* and *The Site Reliability
  Workbook*: release engineering, configuration design, incident response.
