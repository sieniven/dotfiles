# Validation and policy

Four layers, each catching what the others cannot. Run all that the repo
lists, in this order, and report each layer's result separately: one green
layer proves nothing about the next.

| Layer | Tool | Catches | Needs |
|-------|------|---------|-------|
| Syntax and schema | `cfn-lint` (or `cfn-validate`) | Unknown properties, wrong types, bad intrinsics, invalid values per region | Nothing |
| House policy | `cfn-guard` with the repo's rules | Naming, tags, retain policies, open ingress, missing descriptions | The rule files |
| Security patterns | `cfn_nag`, Checkov, Trivy | Generic anti-patterns (wide IAM, unencrypted stores, no flow logs) | Nothing |
| Service-side | Change-set creation (pre-deployment validation) | Property validation against the live schema, name conflicts, quota and delete-readiness warnings | Credentials |

Use one local schema validator, the one the project already configures;
do not add a second by default.

## cfn-lint

```sh
cfn-lint templates/**/*.yaml
cfn-lint --format json --regions <region> template.yaml
```

- Rule IDs: `E` errors, `W` warnings, `I` informational. Errors fail the
  build; decide in the repo whether warnings do.
- Suppress on the one resource, with the reason in a comment beside it:

  ```yaml
  Metadata:
    cfn-lint:
      config:
        ignore_checks: [W3005]   # why
  ```

  A finding reported against a parameter can only be suppressed in the
  template's top-level `Metadata`; do that only for such findings and name
  the parameter in the reason. Never in `.cfnlintrc` for the whole repo.
  Precedence, lowest first: the rc file, template metadata, command-line
  flags.
- `--regions` matters for templates deployed to several regions: resource
  types and property values differ by region.

## cfn-guard

```sh
cfn-guard validate --rules rules/ --data templates/ --show-summary fail
cfn-guard validate -r rules/x.guard -d template.yaml --output-format json
cfn-guard test --rules-file rules/x.guard --test-data rules/x_tests.yaml
```

Guard has no built-in rules: every rule comes from the repo, or from the
AWS Guard Rules Registry if the repo adopts it. Rules are where a house
convention becomes enforceable, so a convention and its rule change in the
same pull request.

Patterns that hold up:

- **Select, then assert.** Bind the resources a rule is about, and run the
  rule only when there are some:

  ```
  let retained = Resources.*[ Type in ["AWS::EC2::VPC", "AWS::EC2::Subnet"] ]
  rule retain_stateful when %retained !empty {
      %retained {
          DeletionPolicy == "Retain"   <<VPCs and subnets need Retain>>
          UpdateReplacePolicy == "Retain"
      }
  }
  ```

  Without the `when ... !empty` guard a template that has none of those
  resources fails or is skipped in confusing ways.
- **Accept both the literal and the `!Sub` form** of a name. In the parsed
  template `!Sub "a-${Env}-b"` is `{"Fn::Sub": "a-${Env}-b"}` (or a list
  when it has a variable map), so a rule on `Value` alone misses it:

  ```
  Value == %name_literal or
  Value.'Fn::Sub' == %name_template or
  Value.'Fn::Sub'[0] == %name_template
  ```

- **A value that arrives through a parameter cannot be checked by Guard.**
  Constrain the parameter instead (`AllowedPattern`, `AllowedValues`), for
  example a CIDR parameter whose pattern refuses any mask shorter than
  `/16`, so a parameter file cannot open a rule to the internet.
- **Inline or standalone, check both.** A security group's rules may be
  inline (`SecurityGroupIngress` on the group) or separate
  `AWS::EC2::SecurityGroupIngress` resources; a rule that reads only one
  form is bypassed by the other. Where a rule depends on the group's name
  (open ingress only on groups marked public), require that such ingress be
  declared inline, so the name is in reach.
- **Suppression is something the rule implements,** not something Guard
  gives for free. A common shape is a list under the resource's metadata
  that the rule's selector excludes:

  ```
  let checked = Resources.*[
      Metadata.guard.SuppressedRules not exists or
      Metadata.guard.SuppressedRules[*] != "tags_name_and_product"
  ]
  ```

  Offer it only for the rules that need an escape (an adopted resource that
  keeps its old name until a rename), and say in the rule file that no other
  rule can be suppressed.
- **Encode what the service will refuse.** If an API rejects a value the
  linter accepts (the character set of a security group rule description,
  a length limit), a rule that fails in seconds saves a failed stack update.
- **Test the rules.** `cfn-guard test` runs a rule file against sample
  inputs with expected `PASS`/`FAIL`/`SKIP`; a rule that silently skips
  everything is the usual bug.

## Security scanners

`cfn_nag` (run from its container image where the gem will not install),
Checkov and Trivy carry generic rule sets. `cfn_nag` has had no release
since mid-2022: keep it where a repo already runs it, and choose Checkov
or Trivy for a new one. Fix the finding; if it does not apply, suppress on
the resource with a reason:

```yaml
Metadata:
  cfn_nag:
    rules_to_suppress:
      - id: W60
        reason: Flow logs for this VPC are owned by another stack.
```

## Service-side validation

Creating a change set runs CloudFormation's pre-deployment validation and
provisions nothing, which makes it the pre-flight for any environment.

- Checks, with their mode: property validation against the resource schema
  (`FAIL`), resource name conflict (`FAIL`), S3 bucket not empty on delete
  (`WARN`), and on change-set creation only: service quota, AWS Config
  recorder conflict and ECR repository delete readiness (all `WARN`).
- A `FAIL` finding stops the operation before any resource is touched. The
  same validation also runs at the start of a direct create or update.
- Results come from `describe-events`, not from `describe-stack-events`:

  ```sh
  aws cloudformation describe-events --change-set-name <arn> --region <region>
  ```

  Read the events whose `EventType` is `VALIDATION_ERROR`: `ValidationName`,
  `ValidationStatus`, `ValidationFailureMode`, `ValidationStatusReason`,
  `ValidationPath` and `LogicalResourceId`. No such events means it passed.
- `--disable-validation` exists; do not pass it unless the user asks.
- A passed validation is not a successful deploy: IAM permissions at
  provisioning time, an image that does not exist in the region, and
  service-specific constraints only show when the change runs.

## Hooks

CloudFormation Hooks evaluate an operation at the service, before it is
provisioned, whoever submitted it. A hook targets resources, whole stacks,
change sets or Cloud Control API calls, runs in `FAIL` or `WARN` mode, and
is written as Guard rules, a Lambda function, a Control Tower proactive
control or a custom hook. A Guard hook can reuse the repo's own rule
files. Hooks do not run for the deletes of the cleanup phase (a resource
removed from the template, or the old copy after a replacement). They are
the control that cannot be skipped by running a different command
locally: local checks give the fast feedback, hooks give the guarantee.

## Sources

The service-side validation and `describe-events` details follow the
`aws-cloudformation` skill in AWS's Agent Toolkit
(<https://github.com/aws/agent-toolkit-for-aws>, Apache-2.0), checked
against its references on 2026-11-28. Tool behaviour:
<https://github.com/aws-cloudformation/cfn-lint>,
<https://docs.aws.amazon.com/cfn-guard/latest/ug/what-is-guard.html>.
