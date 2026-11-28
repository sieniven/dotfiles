# Change sets, deploys, protections and quotas

Checked against the CloudFormation user guide, API reference and AWS CLI
reference on 2026-11-28. Flags move; when one is refused, read
`aws cloudformation <command> help` for the installed CLI.

## How a property updates

- The resource's page in the Template Reference gives **Update requires**
  for each property: *No interruption*, *Some interruptions* or
  *Replacement*. Read the property's description too: some pages qualify
  the label there (an instance's block device mappings are labelled as an
  interruption, and the description says that changing anything but
  `DeleteOnTermination` replaces the instance).
- The registry schema is a fast cross-check of what is immutable:

  ```sh
  aws cloudformation describe-type --type RESOURCE \
    --type-name AWS::EC2::Subnet --query Schema --output text \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("createOnlyProperties"))'
  ```

  A property listed under `createOnlyProperties` cannot change without a
  new resource. The list is not complete: `conditionalCreateOnlyProperties`
  replace in some cases only, so an absent property is not proof of an
  in-place update.
- On replacement CloudFormation usually creates the new resource first,
  repoints what depends on it, and deletes the old one in the cleanup
  phase. Adding or removing a property that requires replacement replaces
  the resource even when the effective value is the same.
- "You can't perform an update that causes a custom-named resource to be
  replaced": a resource with a fixed physical name must be given a new
  name, or changed by the twin pattern.
- The change set is the final word for this stack and this change. The
  documentation says what can happen; the change set says what will.

## A reviewed change set

```sh
aws cloudformation create-change-set \
  --stack-name <stack> \
  --change-set-name <stack>-<short-sha> \
  --description "<full commit sha>" \
  --change-set-type UPDATE \
  --template-body file://<template> \
  --parameters file://<parameter-file> \
  --tags <the stack's full tag set> \
  --capabilities CAPABILITY_NAMED_IAM \
  --region <region>

aws cloudformation wait change-set-create-complete \
  --stack-name <stack> --change-set-name <name> --region <region>

aws cloudformation describe-change-set \
  --stack-name <stack> --change-set-name <name> \
  --include-property-values --region <region>

aws cloudformation describe-events --change-set-name <change-set-arn> \
  --region <region>
```

`execute-change-set` is the step a person takes, after reading the above.

- `--change-set-type` is `CREATE` for a stack that does not exist, `UPDATE`
  for one that does, `IMPORT` for an import
  (`import-and-refactor.md`).
- `--capabilities` is needed only when the template creates IAM resources:
  `CAPABILITY_IAM`, or `CAPABILITY_NAMED_IAM` when they carry fixed names.
- **Parameters left out do not keep their value here.** With
  `create-change-set` and `update-stack` a parameter missing from the call
  takes the template's default, or fails when it has none, unless it is
  passed with `UsePreviousValue=true`. Pass the whole parameter file.
- **Tags.** `update-stack` leaves the stack's tags alone when the tag
  option is omitted and removes them all when it is given empty. `deploy`
  always sends exactly the tags it was given. The safe rule for every
  command: pass the stack's full tag set every time.
- A change set records the values it resolved when it was created (SSM
  parameter types included). Executing it days later applies those, not
  today's.
- Executing one change set invalidates the stack's others: the user guide
  says they are deleted, the API also has an `OBSOLETE` execution status
  for a change set whose stack has since been updated. Either way, create
  a new one after any other update.
- For a new stack, `--on-stack-failure` (`ROLLBACK`, `DO_NOTHING`,
  `DELETE`) chooses what a failed creation leaves behind.

### Reading the result

| Field | Values | Read it as |
|-------|--------|------------|
| `Action` | `Add`, `Modify`, `Remove`, `Import`, `Dynamic`, `SyncWithActual` | What happens to the resource |
| `Replacement` | `True`, `False`, `Conditional` | Whether a new physical resource is created |
| `PolicyAction` | `Delete`, `Retain`, `Snapshot`, `ReplaceAndDelete`, `ReplaceAndRetain`, `ReplaceAndSnapshot` | What the retain policies do to the old resource |
| `Scope` | `Properties`, `Tags`, `Metadata`, and others | Which part of the resource changes |
| `Details[].Target.Name` | A property name | The property that drives the change |
| `Details[].Target.RequiresRecreation` | `Never`, `Conditionally`, `Always` | That property's update behaviour |
| `Details[].Target.BeforeValue`, `AfterValue` | Values, with `--include-property-values` | From what, to what (large values are truncated) |
| `Details[].ChangeSource`, `CausingEntity` | A parameter, another resource, a direct edit | Why the property changes |
| `Details[].Evaluation` | `Static`, `Dynamic` | `Dynamic` cannot be decided until execution |

- `Replacement: Conditional` comes from a `Dynamic` evaluation: the new
  value depends on something else that changes in the same operation.
  Assume replacement.
- `PolicyAction` is the check that the retain policies are in place:
  a replacement on a stateful resource should read `ReplaceAndRetain`,
  never `ReplaceAndDelete`.
- A tag-only `Modify` on every resource means a stack-level tag changed.
- Status `FAILED` with a reason that the submission "didn't contain
  changes" means the stack already matches. Delete the empty change set.
- Status `FAILED` with validation findings means pre-deployment
  validation refused it: read `describe-events`
  (`validation-and-policy.md`).

## `aws cloudformation deploy`

`deploy` creates a change set and executes it in one command. It decides
`CREATE` or `UPDATE` by itself.

- **It keeps previous parameter values.** For an existing stack, a
  parameter not named in `--parameter-overrides` keeps the stack's current
  value; a parameter new to the stack takes the template default. So
  deleting a line from a parameter file changes nothing. To clear an
  optional parameter set it to `""`, and keep the line.
- `--no-execute-changeset` stops after creating the change set, for a
  person to review and execute. The change set gets a generated name:
  where change sets must be named for the commit, use `create-change-set`.
- An empty change set is a zero exit by default on CLI v2;
  `--fail-on-empty-changeset` makes it an error.
- A template over 51,200 bytes needs `--s3-bucket`; without one `deploy`
  refuses it.
- It has no import, no Express mode, no drift-aware mode and no way to
  disable validation. Those need `create-change-set` or the stack commands.
- For production, the only safe forms are `--no-execute-changeset` or not
  using `deploy` at all.

## Protections

- **Termination protection**: `aws cloudformation
  update-termination-protection --enable-termination-protection
  --stack-name <stack>`. It blocks stack deletion. Set on the root stack,
  it covers nested stacks. Enable at creation; disabling it is never part
  of a routine change.
- **Retain policies**: `DeletionPolicy` takes `Delete`, `Retain`,
  `RetainExceptOnCreate` or `Snapshot`; `UpdateReplacePolicy` takes
  `Delete`, `Retain` or `Snapshot`. Write them as literals. The default is
  `Delete` (RDS clusters and standalone instances default to `Snapshot`).
- **Stack policy**: a JSON document that allows or denies update actions
  (`Update:Modify`, `Update:Replace`, `Update:Delete`) per logical ID. It
  applies only during stack updates. Once set it cannot be removed, only
  replaced (`set-stack-policy`) or overridden for one update. A stack with
  a stack policy cannot take part in a stack refactor.
- **Service-level protection** (an instance's API termination protection,
  a database's deletion protection) is the last line: it fails a delete
  that everything above let through.

## Values resolved at deploy time

- **SSM parameter types** (`AWS::SSM::Parameter::Value<...>`): the value
  is read from Parameter Store on every create, update and change-set
  creation. "Use previous value" keeps the parameter's key, not its value:
  the latest value is always fetched. A consumer therefore picks up a
  producer's new value on its next deploy, whether or not the consumer's
  template changed.
- **`{{resolve:ssm:name}}`** without a version resolves to the latest
  version on each stack create or update. Pin a version where a silent
  change would matter.
- **`{{resolve:secretsmanager:...}}`** can be used in any resource
  property. The secret is read only when the resource is created, or
  updated for some other reason. Rotating the secret does not change the
  resource until something else does.
- **`{{resolve:ssm-secure:...}}`** works only in the handful of properties
  AWS lists for it.
- Drift detection does not look at dynamic references.
- **Exports** work within one account and region. An export cannot be
  changed or removed, nor its stack deleted, while another stack imports
  it; `aws cloudformation list-imports --export-name <name>` shows who
  does.
- **`Fn::GetStackOutput`** reads another stack's output by stack and
  output name, across regions and accounts, with no export and no lock on
  the producer. AWS calls it a weak reference: the value is read when the
  consuming stack is created or updated and the consumer is not told when
  it changes. It has placement limits (not inside a `Sub` variable map,
  `Outputs` or `Conditions`); read its reference page before using it.
- **`NoEcho`** masks a parameter in calls that describe the stack and its
  events. It does not mask the value in `Metadata` or `Outputs`, and a
  value used in a resource's primary identifier may be shown in plain
  text. It is not a place for secrets.

## Stack-level tags

- Tags given to the stack propagate to every resource that supports it,
  and changing them later is a stack update that touches all of those
  resources. Up to 50; CloudFormation adds its own `aws:cloudformation:*`
  tags, which do not count.
- Propagation varies by type. Stack tags do not reach EBS volumes created
  from an instance's block device mappings: the instance's
  `PropagateTagsToVolumeOnCreation` tags those.

## Development shortcuts

- **Direct deploys** are fine where the repo says an environment may
  deploy without review.
- **Express mode** returns as soon as configuration is applied, before
  resources are ready to serve:

  ```sh
  aws cloudformation update-stack ... \
    --deployment-config '{"Mode":"EXPRESS","DisableRollback":false}'
  ```

  It is accepted by `create-stack`, `update-stack`, `delete-stack` and
  `create-change-set` (stored with the change set). State
  `DisableRollback` explicitly: AWS's user guide and API reference
  disagree on its default in Express mode. Not for StackSets; custom
  resources still wait. Never for a stack whose readiness something else
  depends on straight away.
- **Disabling rollback** keeps a failed stack as it stopped, for
  inspection. Development only.

## Quotas worth knowing

| Limit | Value |
|-------|-------|
| Template body passed inline | 51,200 bytes |
| Template in S3 | 1 MB |
| Resources per template | 500 |
| Parameters, outputs, mappings per template | 200 each |
| Template description | 1,024 bytes |
| Parameter value | 4,096 bytes |
| Dynamic references per template | 60 |
| Stack name | 128 characters |
| Tags per stack | 50 |
| Resources per import operation | 200 |
| EC2 user data | 16 KB raw, before base64 |

A migration that keeps old and new resources side by side can push a
template over the inline limit for one release. Split the migration into
batches, or move to an S3 bucket first.

## Events

`describe-events` is the newer events API: scoped by `--stack-name`,
`--change-set-name` or `--operation-id`, filterable with `--filters
FailedEvents=true`, and carrying validation, provisioning and hook errors
(`EventType`: `STACK_EVENT`, `PROGRESS_EVENT`, `VALIDATION_ERROR`,
`PROVISIONING_ERROR`, `HOOK_INVOCATION_ERROR`). `describe-stacks` lists
the recent operation IDs under `LastOperations`. `describe-stack-events`
still works and has none of this.
