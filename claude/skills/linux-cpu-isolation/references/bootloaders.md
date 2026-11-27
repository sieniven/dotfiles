# Getting parameters onto the kernel command line

Companion to `SKILL.md`. The command line is written by a bootloader's
configuration, generated from other files, and read by the kernel once. A
change is three steps that can each be skipped by mistake: edit the source,
regenerate, reboot. Distributions differ in detail; read the host before
writing, and treat anything below not confirmed on that host as a
hypothesis.

## Know which mechanism the host uses

```sh
command -v update-grub grub2-mkconfig grubby bootctl kernel-install
ls /etc/default/grub /etc/default/grub.d/ /boot/loader/entries/ /etc/kernel/cmdline 2>/dev/null
cat /proc/cmdline
```

A script picks one mechanism by what is installed and refuses when it finds
none, printing the arguments for an operator to add by hand.

## GRUB with a generated config (Debian, Ubuntu)

- `/etc/default/grub` is a shell fragment sourced by `grub-mkconfig`;
  Debian and Ubuntu then source `/etc/default/grub.d/*.cfg` in name order,
  so a later file overrides an earlier one.
- `GRUB_CMDLINE_LINUX` goes on every entry, recovery included;
  `GRUB_CMDLINE_LINUX_DEFAULT` on the normal entries only. Isolation
  belongs in the second, so a recovery boot comes up unisolated.
- Cloud images ship their own drop-in that assigns
  `GRUB_CMDLINE_LINUX_DEFAULT`. A drop-in that sorts after it and appends
  (`"${VAR:+$VAR }new args"`) keeps what was there; one that assigns
  replaces it, and one that sorts before it is overwritten.
- `update-grub` regenerates `/boot/grub/grub.cfg`. Until it runs, the
  drop-in changes nothing; until the reboot, the generated file changes
  nothing.
- Own one drop-in with a marker line, and refuse when another file under
  `/etc/default/grub*` already sets an isolation parameter: two sources
  for one setting is how a host ends up isolating cores nobody chose.

## BLS entries and grubby (RHEL family, Fedora, Amazon Linux)

- Each installed kernel has an entry under `/boot/loader/entries/` with
  its own arguments. `grubby --info=ALL` prints them;
  `grubby --update-kernel=ALL --args="..."` and `--remove-args="..."`
  edit every entry.
- Whether a kernel installed later inherits the arguments depends on the
  distribution's kernel-install configuration. Check after a kernel update
  with `grubby --info=ALL`; do not assume.
- `--remove-args` takes parameter names without values to remove them
  whatever their value.
- Older Amazon Linux generations use a generated GRUB config instead
  (`grub2-mkconfig -o /boot/grub2/grub.cfg`).

## systemd-boot and unified kernel images

`kernel-install` takes the command line from `/etc/kernel/cmdline`, falling
back to `/usr/lib/kernel/cmdline` and then the running `/proc/cmdline`. A
unified kernel image embeds its command line at build time, so a change
means rebuilding the image.

## Running against next boot

- Running: `/proc/cmdline`.
- Next boot: the generated `grub.cfg`, or every BLS entry, or
  `/etc/kernel/cmdline`. Compare only the isolation tokens, sorted, and
  ignore commented lines.
- "A reboot is pending" is the two differing. A tool that cannot read the
  next boot says it cannot tell, rather than guessing.
- After the reboot the truth is sysfs (`isolated`, `nohz_full`), since a
  kernel can accept a parameter on the command line and ignore it for want
  of the feature.

## Undo

Remove exactly what was written: the owned drop-in or the named arguments,
then regenerate. Runtime side effects of the apply (interrupts moved,
irqbalance restarted) are either reverted too or stated as lasting until
the reboot.

## Things that go wrong

1. Arguments added to `GRUB_CMDLINE_LINUX` on a cloud image and silently
   replaced by the image's own drop-in.
2. The source edited, `update-grub` not run.
3. grubby run on the default kernel only; the next kernel update boots
   without the arguments.
4. Two tools owning the command line (a tuning daemon and a script), each
   rewriting the other's work.
5. A cpulist written with spaces or a trailing comma, which the kernel
   rejects with a log line and no isolation.
6. A reboot of a host that is running a node.
