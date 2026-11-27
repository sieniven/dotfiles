# Idle states, frequency and the clock

Companion to `SKILL.md`. A core that spins never idles, so power states
matter for everything around it: the cores that park, the housekeeping core
that takes the NIC's interrupts, the idle SMT siblings, and the frequency
the busy cores get.

## Idle states

- A CPU with nothing to run enters an idle state; deeper states save more
  and take longer to leave. Each state's exit latency is in
  `/sys/devices/system/cpu/cpuN/cpuidle/stateM/latency` (microseconds),
  with `name`, `residency`, `usage` and `time` beside it.
- Who pays: a thread that parks and is woken by a timer or an interrupt
  starts after the exit latency. So does a NIC interrupt that lands on an
  idle housekeeping core, and that delay is socket wait for the thread
  that reads the socket.
- Limits, narrowest first:
  - per CPU and state, at runtime: write 1 to
    `cpuidle/stateM/disable`;
  - per CPU, at runtime: a latency bound in
    `/sys/devices/system/cpu/cpuN/power/pm_qos_resume_latency_us`;
  - system-wide, for as long as a process holds it: open
    `/dev/cpu_dma_latency`, write a 32-bit latency in microseconds, keep
    the descriptor open;
  - at boot: `intel_idle.max_cstate=`, `processor.max_cstate=`.
- `idle=poll` makes every idle CPU spin. It removes exit latency
  everywhere and it makes an idle SMT sibling compete with the pinned
  thread on the same physical core. With isolated idle siblings, limit
  states per CPU instead and let the siblings sleep deeply.
- Limit the cores whose wake-up is on the path: time-shared cores and the
  interrupt-handling housekeeping core. Leaving the rest alone keeps
  thermal and turbo headroom for the busy ones.

## Frequency

- The governor decides frequency from load; `performance` holds the
  maximum the driver allows. Read
  `/sys/devices/system/cpu/cpuN/cpufreq/scaling_governor` and
  `scaling_driver`.
- Turbo frequency depends on how many cores are active and on which
  instructions they run, so a core's speed moves with its neighbours'
  load. Steady frequency and highest frequency are different goals; state
  which one a setting serves.
- A core that alternates spinning and parking under a load-following
  governor ramps on every wake.
- `turbostat` shows what the hardware did: busy frequency, idle-state
  residency per core, and the SMI count.

## Firmware

System-management interrupts stop every core and are invisible to the
kernel except as missing time. They come from firmware features (power
capping, error reporting, legacy USB emulation). Only BIOS settings remove
them; `turbostat`'s SMI column and `rtla hwnoise` detect them.

## The clocksource

- `/sys/devices/system/clocksource/clocksource0/current_clocksource`
  should read `tsc` on x86. When the kernel judges the TSC unstable it
  falls back to a slower source, and every clock read on the hot path
  becomes a real kernel entry instead of a vDSO call.
- A tickless core needs a clocksource that requires no watchdog.
  `tsc=reliable` and `tsc=nowatchdog` assert that by hand; they are
  appropriate only where the TSC is known invariant and synchronised.
- In a guest, the clocksource and the TSC's behaviour across migration or
  suspend are the hypervisor's. An engine that maps the TSC onto wall
  time must re-anchor after a jump.
- `dmesg | grep -i -E 'clocksource|tsc'` shows a fallback and its reason.

## Wall-clock discipline

- Comparing a local timestamp with a venue's needs both clocks on the
  same time. Run one time daemon against the provider's or the site's
  source, let it slew rather than step, and export its offset as a
  metric.
- A step backwards is a correctness hazard for anything that orders
  events by wall time. Decision logic reads a monotonic clock.
- Measure the offset where the node runs, at the time of the measurement;
  a one-way latency figure is only as good as the offset beside it.

## Reading it back

```sh
grep . /sys/devices/system/cpu/cpu2/cpuidle/state*/{name,latency,disable}
cat /sys/devices/system/cpu/cpu2/cpufreq/scaling_{driver,governor}
cat /sys/devices/system/clocksource/clocksource0/{current,available}_clocksource
turbostat --quiet --interval 5 --num_iterations 1
```

## Sources

`Documentation/admin-guide/pm/cpuidle.rst` (idle-state sysfs, PM QoS),
`Documentation/admin-guide/pm/cpufreq.rst`,
`Documentation/admin-guide/kernel-parameters.txt` (`idle=`, `tsc=`,
`intel_idle.max_cstate`, `processor.max_cstate`),
`Documentation/admin-guide/cpu-isolation.rst` (the checklist: SMT,
frequency, C-states, firmware interrupts).
