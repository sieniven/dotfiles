# EC2 and VPC resources: what replaces, what drops traffic, what is refused

Update behaviours are quoted from the Template Reference pages as read on
2026-11-28. Look the property up again before relying on one; the pages
change, and the change set has the last word.

## Security groups

| Property | Update requires |
|----------|-----------------|
| `GroupName`, `GroupDescription`, `VpcId` on the group | Replacement |
| Inline `SecurityGroupIngress`, `SecurityGroupEgress` on the group | Some interruptions |
| `Description` on a standalone ingress or egress rule | No interruption |
| Anything else on a standalone rule (CIDR, ports, protocol, source or destination group) | Replacement of the rule |

- **A group's name or description cannot change in place**, and a group
  with a fixed `GroupName` cannot be replaced either (the new one would
  collide). Renaming one is the twin pattern: a new group with the same
  rules, a matching rule in every group that admits the old one, attached
  beside the old one on every interface (no restart), then the old one
  detached and deleted.
- **Changing a rule drops traffic.** In AWS's words, CloudFormation
  "removes the existing rule and then adds a new rule", and for a moment
  neither exists. Never narrow or move a rule in one deploy: add the new
  rule beside the old, deploy, check the flow logs, remove the old in a
  second deploy.
- **Relabelling a rule is safe.** A description updates in place and
  never revokes the rule.
- **Descriptions have a character set.** EC2 accepts letters, digits,
  spaces and `._-:/()#,@[]+=;{}!$*`, up to 255 characters; `&` is accepted
  on a rule for an address range but not on one that references a group,
  so leave it out. An apostrophe or a quotation mark is refused, and the
  whole stack update with it. A policy rule that checks the set fails in
  seconds instead.
- **Egress.** A group created with no egress rules gets AWS's allow-all
  egress. Declaring `SecurityGroupEgress` inline replaces that default
  with exactly what is declared. Standalone
  `AWS::EC2::SecurityGroupEgress` resources only add rules; the default
  stays. To restrict egress, declare it inline.
- **Inline or standalone.** Two groups that reference each other must use
  standalone rule resources, or the template has a circular dependency.
  Open-to-the-internet ingress is better inline, where a policy rule can
  read the group's name beside it.
- **The same rule twice is refused** as a duplicate. Two optional CIDR
  parameters holding the same value collide, and so does moving a value
  from one parameter to another in a single deploy: clear the old slot in
  one deploy and fill the new one in the next.
- **References across VPCs.** A rule can name a group in a peered VPC in
  the same region. Across regions it cannot: use the peer's CIDR, or the
  single host address.
- **Quotas.** By default five groups per network interface and 60 rules
  each way per group. Needing more groups on one interface is a sign the
  role is doing too much.
- **A group in use cannot be deleted.** Removing a group that an interface
  still carries, or that another group's rule still names, fails in the
  cleanup phase. Detach and remove references first, in an earlier deploy.
- **Leave the VPC's default group alone.** Attach nothing to it and do not
  try to manage its rules from a template.
- Standalone rules, subnet route table associations and gateway
  attachments are not covered by drift detection. A rule added by hand is
  found by comparing the live group with the template.

## VPCs, subnets and routes

| Property | Update requires |
|----------|-----------------|
| Subnet `AvailabilityZone`, `AvailabilityZoneId`, `CidrBlock`, `VpcId` | Replacement |
| Subnet `MapPublicIpOnLaunch` | No interruption |
| Tags on any of them | No interruption |

- **Zone names are per account; zone IDs are not.** `us-east-1a` in one
  account may be another account's `us-east-1c`; `use1-az1` is the same
  place for everyone. Use the ID whenever a zone is compared with anyone
  outside the account, and consider naming zonal resources by it.
- A subnet placed by zone name stays placed by zone name: switching the
  same subnet to `AvailabilityZoneId` is a replacement even when it is the
  same zone. Name by ID through a mapping, place by whichever the subnet
  was created with.
- A subnet that must sit in a particular physical zone takes the zone ID
  as a parameter, so the choice is explicit.
- Retain VPCs and subnets (`DeletionPolicy` and `UpdateReplacePolicy`).
  Their IDs are what everything else hangs from.
- **Every VPC has a main route table**, used by any subnet without an
  explicit association. Associate every subnet explicitly and leave the
  main table with only its local route, so that a forgotten association
  reaches nothing rather than everything.
- **One owner per route.** A `0.0.0.0/0` route belongs to the stack that
  owns the gateway; a peering route to the stack that owns the peering; a
  gateway endpoint's prefix-list routes to the endpoint, through its
  `RouteTableIds`, never to a route resource.
- **Peering.** One connection per pair of VPCs, created by the requester.
  Routes go in every route table of both sides. Peering is not transitive,
  but a host that forwards traffic (a VPN server, a NAT instance) lends
  its VPC's peerings to everything behind it. A cross-region peering's
  tags are kept separately on each side: import each side with the tags
  found there.
- **Flow logs** before narrowing access, not after: they are how a rule
  for "everything in the private range" is replaced by rules naming the
  hosts that really connect.
- **Elastic IPs** are retained and published (an SSM parameter), because
  third parties allowlist them. An auto-assigned public address changes on
  stop and start; anything allowlisted needs an Elastic IP.

## Instances

| Property | Update requires |
|----------|-----------------|
| `ImageId`, `KeyName`, `SubnetId`, `LaunchTemplate`, `NetworkInterfaces` | Replacement |
| `InstanceType`, `UserData`, `SecurityGroupIds` | Some interruptions |
| `BlockDeviceMappings` | Only `DeleteOnTermination` changes in place; anything else replaces the instance |
| `PropagateTagsToVolumeOnCreation` | No interruption |

- **A long-lived instance pins everything that would replace it**: the
  image by ID (an SSM "latest image" parameter resolves again on every
  stack operation, and a newly published image then replaces the
  instance), the launch template version (not "latest"), the key pair.
- **Changing `UserData` restarts** an EBS-backed instance, and does not
  re-run a first-boot script: cloud-init runs user data once unless told
  otherwise. Changing it is an interruption with no effect on the machine's
  setup.
- **Changing `InstanceType`** stops and starts the instance where the old
  and new types are compatible.
- **Keep the disk when the instance goes**: `DeleteOnTermination: false`
  on the root volume of a machine whose contents matter. Grow a disk with
  the EC2 API (`modify-volume`), not through the template.
- `PropagateTagsToVolumeOnCreation` tags the volumes declared in the
  instance's block device mappings, at creation. Stack-level tags do not
  reach those volumes by themselves.
- **User data is capped at 16 KB**, raw, before base64. A template that
  embeds a program in user data is on a budget: compress it, or fetch it
  at boot.
- **The key pair seeds the machine at launch** and nothing more; changing
  `KeyName` later replaces the instance. Manage access after launch on the
  machine or through Session Manager.
- A security group attached by hand to an instance the template also
  manages is drift; where instances are hand-run by design, groups are
  attached by CLI and the template does not own the instance at all.

## IAM in the same templates

- A fixed `RoleName`, `ManagedPolicyName` or `InstanceProfileName` needs
  `CAPABILITY_NAMED_IAM` and makes the resource irreplaceable. Fix names
  only where something outside the stack refers to them.
- One role and one instance profile per compute role; inline policies on
  the role unless a policy must also attach to roles outside the stack.
- Scope a workload's role to where it runs: a condition on the source VPC
  for traffic through a gateway endpoint in the same region, on the
  source address where there is none.
- Grant by explicit action list rather than by attaching an AWS managed
  policy: managed policies change without a review on your side.

## Sources

Template Reference pages for `AWS::EC2::SecurityGroup`,
`SecurityGroupIngress`, `SecurityGroupEgress`, `Subnet` and `Instance`
under <https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/>;
EC2 user data limits at
<https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html>.
