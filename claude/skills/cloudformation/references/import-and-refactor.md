# Import, moves between stacks, and renames

Three different jobs, three mechanisms:

| Goal | Mechanism | New physical resource? |
|------|-----------|------------------------|
| Bring a hand-built resource under a stack | Import change set | No |
| Move a resource to another stack, rename a logical ID, split or merge stacks | Stack refactoring where the type allows it; otherwise retain, remove, import | No |
| Change an immutable property (a fixed name, a description, a zone) | A twin beside the original | Yes, by definition |

Checked against the CloudFormation user guide and API reference on
2026-11-28.

## Importing

### What the service requires, and what it does not check

- Every resource being imported has a `DeletionPolicy` in the template.
  Any value is accepted; use `Retain`, with `UpdateReplacePolicy: Retain`,
  so that deleting or breaking the stack can never remove what was adopted.
- The template describes the whole stack: what it already holds, unchanged,
  plus the resources to import, each with its identifier.
- **An import operation holds imports only.** It cannot create a resource,
  delete one, or change a property of one already in the stack, and it
  fails if a parameter change would cause any of those.
- CloudFormation checks that the resource exists, that the template's
  properties are valid for the type, that required properties are present
  and that the resource is not in another stack in the region. For global
  types (IAM roles, hosted zones) check the other regions yourself.
- **It does not check that the template matches the live resource.** A
  property written wrongly is accepted and becomes the stack's belief. The
  difference shows later as drift, or as an unexpected change in the next
  update. Hence the discipline below.
- At most 200 resources per operation, one level of nested stacks.
- Whether a type can be imported, and whether drift detection covers it,
  is in the user guide's "Resource type support" table. The two are
  separate columns: subnet route table associations, internet gateway
  attachments and standalone security group rules can be imported but are
  not covered by drift detection, so the check after the import says
  nothing about them. Compare those by hand.

### Method

1. **Read the live resource the same day**: its properties and its tags,
   in the region it is imported in, from the API. Never from memory, a
   diagram or an old note.
2. **Write the template to state exactly that**, existing name and tags
   included, each resource retained. Where the repo's policy rules demand
   the house name and tags, the adopted resource carries the rule's
   suppression with the reason, or the template switches its tags on a
   parameter (below).
3. **List the identifiers**:

   ```sh
   aws cloudformation get-template-summary --template-body file://<template> \
     --query ResourceIdentifierSummaries
   ```

   and write the import file:

   ```json
   [
     {
       "ResourceType": "AWS::EC2::VPC",
       "LogicalResourceId": "Vpc",
       "ResourceIdentifier": { "VpcId": "vpc-0123456789abcdef0" }
     }
   ]
   ```

4. **Create the import change set.** The type is `IMPORT` whether the
   stack already exists or is created by the import:

   ```sh
   aws cloudformation create-change-set \
     --stack-name <stack> --change-set-name <stack>-<short-sha> \
     --change-set-type IMPORT \
     --resources-to-import file://<import-file> \
     --template-body file://<template> \
     --parameters file://<parameter-file> --region <region>
   ```

   Every resource in it should read `Action: Import`. Anything else means
   the template is doing more than importing.
5. **A person executes it.** Then, before any other operation, run drift
   detection on the stack. `MODIFIED` on an imported resource is a
   property the template states differently from reality: correct the
   template, not the resource.
6. **Enable termination protection** on a production stack, and update the
   repo's inventory of what is still unmanaged in the same pull request.

### Two stages from one template

Things an import cannot carry (the SSM parameters that publish the new
IDs, flow logs, new associations, the convention's names) arrive in an
ordinary update straight after. One template can serve both:

```yaml
Parameters:
  Stage:
    Type: String
    Default: managed
    AllowedValues: [import, managed]
Conditions:
  Managed: !Equals [!Ref Stage, managed]
Resources:
  Vpc:                      # imported
    Type: AWS::EC2::VPC
    DeletionPolicy: Retain
    UpdateReplacePolicy: Retain
    Properties: { ... }
  VpcIdParameter:           # arrives with the first managed deploy
    Type: AWS::SSM::Parameter
    Condition: Managed
    Properties: { ... }
```

Import with `Stage=import`; every deploy after uses the default. The same
switch can select between the tags found and the convention's tags, which
makes the rename the first reviewed change set after the import, tags
only.

### Finding what to import

The IaC generator scans a region for resources no stack manages and
drafts a template for the ones chosen, which can then be imported as a
stack. Treat the draft as a first pass: read every property against the
live resource, and bring names, tags and retain policies to the repo's
rules before importing.

### What cannot simply be imported

- **An implicit association.** A subnet with no explicit route table
  association uses the VPC's main table, and that relationship is not a
  resource. It can be made explicit later by adding an association, which
  is a change, not an import.
- **Anything in another stack.** Remove it from that stack first, retained.
- **A resource whose type does not support import.** Check before removing
  it from anywhere: once out of its stack it cannot be brought back.

### Importing by name

`create-change-set --import-existing-resources` (on an ordinary `CREATE`
or `UPDATE` change set) adopts resources that already exist under the
fixed name the template gives them, without an import file. It works only
for resources with a static custom name, a `DeletionPolicy` of `Retain` or
`RetainExceptOnCreate`, and a type that supports import. Resources without
a custom name (instances, most network resources) still need an import
change set. `aws cloudformation deploy` has no such option.

## Moving a resource between stacks

**Stack refactoring** moves resources between stacks, renames logical IDs,
and splits or merges stacks in one operation, without touching the
resources:

```sh
aws cloudformation create-stack-refactor \
  --stack-definitions StackName=<a>,TemplateBody@=file://a.yaml \
                      StackName=<b>,TemplateBody@=file://b.yaml \
  --resource-mappings file://mappings.json \
  --enable-stack-creation --region <region>
aws cloudformation describe-stack-refactor --stack-refactor-id <id>
aws cloudformation list-stack-refactor-actions --stack-refactor-id <id>
```

Read the listed actions; a person runs `execute-stack-refactor`.

Its limits decide whether it applies:

- It cannot create or delete a resource, change a property, or add or
  change a parameter, condition or mapping. The templates before and after
  must differ only in where resources live and what they are called.
- No stack may be left empty; a stack with a stack policy cannot take
  part; up to five stacks per operation from the CLI.
- A resource that uses a pseudo parameter whose value differs between the
  stacks (a name built from `AWS::StackName`) cannot move.
- Only fully mutable types are supported, and some are excluded outright,
  Elastic IPs and launch templates among them. Check the list for every
  type in the move.

**Retain, remove, import** is the fallback, and works for any type that
supports import:

1. Make sure the resource has `DeletionPolicy: Retain` in the source
   stack, and that this is deployed.
2. Remove it from the source template, with the parameters and outputs
   that belonged to it, and update the source stack. The resource is now
   unmanaged but untouched.
3. Import it into the target stack, as above.

Between steps 2 and 3 nothing manages the resource: do both in one
sitting. A whole stack can move the same way: delete the old stack with
every resource retained, import them all into the new one.

## Changing what cannot change: the twin

When a property is immutable and the resource has a fixed name, or
replacement would drop traffic or data, do it in separate reviewed steps:

1. **Add the twin** with the new value and a different physical name.
   Wherever something admits or references the original, add the same
   reference to the twin, so the two are equivalent.
2. **Attach or route to both.** For a security group this is attaching
   the twin beside the original on every interface that carries it, which
   needs no restart.
3. **Verify from evidence** that the twin carries the traffic.
4. **Detach the original**, then remove it and the references to it.

A template holding both generations is at its largest in the middle:
watch the inline size limit and split into batches if it gets close.

A tag is not a physical name. Renaming a resource whose name is only its
`Name` tag is an in-place tag update, with no twin and no replacement.
