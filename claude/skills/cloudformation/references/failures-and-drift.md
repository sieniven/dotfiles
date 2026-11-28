# Failed stacks, stuck stacks and drift

Everything here up to the recovery commands is read-only. The recovery
commands change the stack's record and are a person's decision.

## Triage of a failed operation

1. **Get only the failures**, from the newer events API:

   ```sh
   aws cloudformation describe-events --stack-name <name-or-arn> \
     --filters FailedEvents=true --region <region>
   ```

   `describe-stack-events` has no such filter and does not carry validation
   results. A client-side `--query` is not a substitute for the filter. If
   the filtered call returns nothing, call it without the filter and look
   for the earliest status that is not a success, or one that never left
   `IN_PROGRESS`. For a deleted stack use its ARN.
2. **Read every failed event**, not the first. CloudFormation provisions in
   parallel, so several resources can fail independently in one operation.
   Keep `LogicalResourceId`, `ResourceType`, `ResourceStatus`,
   `ResourceStatusReason`, `Timestamp` and `EventType`.
3. **Separate real failures from cancellations.** A reason with a specific
   service error is a real failure. A reason that is only "Resource creation
   cancelled" (or the update equivalent) is fallout from the rollback and
   says nothing about that resource: it may have a defect of its own that
   the next attempt will expose. Say so.
4. **Follow nested stacks.** A failed `AWS::CloudFormation::Stack` resource
   carries a generic reason; the real one is in the child stack's events,
   under the child's physical ID.
5. **Group by cause.** Several "not authorized" errors usually share one
   cause, the deploying role. List every denied action and resource, so the
   role is fixed in one pass rather than one deploy per missing permission.
6. **Say where the fix lives.** Template-level: an invalid property, a name
   that already exists, a missing dependency. Environment-level: a
   permission, a quota, a resource in the wrong state, a deletion
   protection. Never propose a template edit for an environment problem.

| Reason contains | Usually means |
|-----------------|---------------|
| `is not authorized to perform` | The deploying role lacks an action |
| `already exists` | A fixed physical name collides with a live resource |
| `Invalid`, `does not match pattern` | A property value the service refuses |
| `Rate exceeded`, `Throttling` | API throttling; retry later or reduce parallel changes |
| `timed out`, `did not stabilize` | The resource never became ready: a dependency, a quota, a health check |
| `is not empty` on delete | A bucket or repository still holds data |
| `not found` | A referenced image, key or role does not exist in this region or account |
| `cannot be deleted`, `DependencyViolation` | Something still uses it, or a protection is on |
| A custom-named resource "requires replacing" | A resource with a fixed name needs replacement, which CloudFormation will not do: see `ec2-and-vpc.md` and the twin pattern |

When the event reason is too generic, look at CloudTrail for errors in the
minute either side of the first failure:

```sh
aws cloudtrail lookup-events --start-time <t-60s> --end-time <t+60s> \
  --region <region> --max-results 50
```

Keep the events whose `errorCode` or `errorMessage` is set: the service's
own error is usually more specific than what CloudFormation relayed.

## Stack states and what each allows

| Status | Meaning | What can be done |
|--------|---------|------------------|
| `REVIEW_IN_PROGRESS` | A create-type change set exists; the stack has no template or resources yet | Execute the change set, or delete the change set and the empty stack |
| `ROLLBACK_COMPLETE` | Creation failed and was rolled back | Only delete; the stack cannot be updated |
| `CREATE_FAILED`, `UPDATE_FAILED` | The operation failed and rollback was disabled, so what was provisioned is still there | Fix and retry or update (with rollback still disabled), or `rollback-stack` to the last stable state |
| `UPDATE_ROLLBACK_COMPLETE` | An update failed and the previous configuration is back | Fix the cause, update again |
| `UPDATE_ROLLBACK_FAILED` | The rollback itself failed | Fix what blocks it, then `continue-update-rollback` |
| `DELETE_FAILED` | Some resources would not delete | Clear the blocker and delete again, or delete while retaining the named resources |
| `IMPORT_ROLLBACK_COMPLETE` | An import failed and the stack is back on its previous template | Fix the template or identifiers, import again |
| `*_IN_PROGRESS` | An operation is running | Wait; no second operation can start |
| `UPDATE_COMPLETE_CLEANUP_IN_PROGRESS` | The update succeeded and the originals of replaced resources are being deleted | Wait, then read the events for a `DELETE_FAILED` |

## Recovery, and what each one costs

- **A failed cleanup does not undo the update.** CloudFormation tries
  three times to delete an old resource, then drops it from the stack and
  finishes `UPDATE_COMPLETE`, with a `DELETE_FAILED` event for it. The old
  resource still exists, still costs money, and nothing manages it. Find
  it and delete or adopt it.
- **`continue-update-rollback`** retries the rollback. With
  `--resources-to-skip` (only resources in `UPDATE_FAILED` can be named)
  it marks them `UPDATE_COMPLETE` without touching them: the stack reaches
  a stable state, and its record now disagrees with reality for each one.
  AWS's warning is that they must be made consistent before the next
  update, or the stack can become unrecoverable. Fix the real cause first
  if it can be fixed; skip only what truly cannot roll back; write down
  what was skipped and reconcile it straight afterwards.
- **Deleting a stack with retained resources** (`delete-stack
  --retain-resources`, accepted only from `DELETE_FAILED`) orphans them.
  They keep running and are no longer managed.
- **`ROLLBACK_COMPLETE` after a failed create** leaves a stack that holds
  nothing and blocks the name. Delete it before the next attempt.
  Resources with `DeletionPolicy: Retain` that were created before the
  failure stay behind, and their fixed names collide on the retry.
  `RetainExceptOnCreate` behaves like `Retain` except in the operation
  that created the resource: if that operation rolls back, the resource
  is deleted. `execute-change-set --retain-except-on-create` applies the
  same to every new resource in that operation.
- **Disabling rollback** (`--disable-rollback`, `--on-stack-failure
  DO_NOTHING`) keeps what was provisioned when an operation fails, for
  inspection and retry. Useful in development; in production a stack
  parked half-updated is its own incident.
- **A failed change set** whose reason is "The submitted information didn't
  contain changes" or "No updates are to be performed" is not a failure:
  the template and parameters match the stack.

## Drift

Drift is a difference between a resource's live properties and what the
stack's template says, caused by a change made outside CloudFormation.

```sh
aws cloudformation detect-stack-drift --stack-name <stack> --region <region>
aws cloudformation describe-stack-drift-detection-status \
  --stack-drift-detection-id <id> --region <region>
aws cloudformation describe-stack-resource-drifts --stack-name <stack> \
  --stack-resource-drift-status-filters MODIFIED DELETED --region <region>
```

- A resource comes back `IN_SYNC`, `MODIFIED`, `DELETED`, or as not
  checked (`NOT_CHECKED`, `UNSUPPORTED`, `UNKNOWN` with a reason). Read the
  unchecked ones as "no information", never as clean.
- Detection looks only at properties set explicitly, in the template or
  through a parameter, and at stack-level tags. A property left to its
  default is invisible, so `IN_SYNC` is not proof that nothing was
  touched.
- Which types are covered is a column of the user guide's resource type
  support table. Standalone security group rules, subnet route table
  associations and gateway attachments are not.
- Something added beside the stack's resources (a rule added to a group
  by hand, a route added to a table) is reported only where the template
  declares that list inline on a covered type. Rules and routes declared
  as separate resources say nothing about extras: find a hand-added one
  by comparing the live group or table with the template.
- **An ordinary update does not look at reality.** In AWS's words, a
  traditional change set compares "your new template with the previous
  template" and does "not account for stack drift". A property changed by
  hand stays changed until an update touches that property.
- **A drift-aware change set does**: `create-change-set --deployment-mode
  REVERT_DRIFT` compares the live state, the last deployed state and the
  new template, and brings drifted resources back to the template even
  where the template did not change. It reports `ResourceDriftStatus` and
  where each value came from. It does not reconcile immutable properties,
  and keeps AWS-managed properties and tag keys the template does not
  mention. `aws cloudformation deploy` cannot create one.
- Each finding is settled one of two ways. **Revert**: put the live
  resource back, by hand or with a drift-aware change set. **Accept**:
  write the live value into the template, so the next change set shows no
  change for it.
- Run detection after every import, on a schedule for production stacks,
  and before any change to a stack that people can also reach by console.
- A resource deleted outside the stack shows as `DELETED` and fails the
  next update that touches it. Remove it from the template (with what
  depends on it), update, then add it back; or import a replacement.

## Sources

The triage procedure follows the `aws-cloudformation` skill in AWS's Agent
Toolkit (<https://github.com/aws/agent-toolkit-for-aws>, Apache-2.0),
checked on 2026-11-28. Stack statuses, failure options and drift:
<https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/>
(`view-stack-events`, `stack-failure-options`, `using-cfn-stack-drift`,
`drift-aware-change-sets`).
