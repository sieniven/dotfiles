# Instruments

Companion to `SKILL.md`. Commands and how to read them. Flags are the
commonly used ones; confirm against the installed version's `--help`. On a
host that trades, everything past "No privilege" is run only when the user
asks for it.

## No privilege

```sh
# Each thread of a process: id, last CPU, mask, switches, name.
for t in /proc/$PID/task/*; do
  stat=$(<$t/stat); set -- ${stat##*) }      # what follows the name: $37 is field 39
  printf '%s cpu=%s %s %s\n' "${t##*/}" "${37}" \
    "$(grep -E 'Cpus_allowed_list|ctxt' $t/status | paste -sd' ')" "$(<$t/comm)"
done
```

Field 39 of `stat` is the last CPU. The command name before it may contain
spaces and parentheses, so the loop cuts at the last `)` before counting.

```sh
cat /proc/$PID/task/$TID/schedstat      # on-CPU ns, waited ns, timeslices
```

The first field lags on a tickless core while one task runs there; take
on-CPU time from `stat`'s tick counts instead. The file exists only on a
kernel built with `CONFIG_SCHED_INFO`; zeros from a sandbox are not a
measurement.

```sh
# Interrupts on core 2 over ten seconds: field 4 is CPU 2's column.
a=$(awk 'NR>1{print $1,$4}' /proc/interrupts); sleep 10
b=$(awk 'NR>1{print $1,$4}' /proc/interrupts)
diff <(echo "$a") <(echo "$b")
```

The header names each column's CPU; CPU *n* is field *n*+2 only while
every lower-numbered CPU is online. Rows shorter than the CPU count (`ERR`,
`MIS`) are totals. A container may mask the file.

## Counting with perf

```sh
perf stat -e context-switches,cpu-migrations,page-faults -t $TID -- sleep 10
perf stat -C 2 -e irq:irq_handler_entry,irq:softirq_entry,sched:sched_switch -- sleep 10
```

Counting adds little. `perf record` sampling raises a performance
interrupt on the core and holds its tick on: use it to profile code, in a
separate run, never to judge quiet.

## Tracepoints by hand

The kernel's own isolation guide uses this procedure.

```sh
T=/sys/kernel/tracing
echo 0 > $T/tracing_on; echo > $T/trace
echo 1 > $T/events/sched/sched_switch/enable
echo 1 > $T/events/irq_vectors/enable
echo 1 > $T/events/timer/tick_stop/enable
echo 1 > $T/tracing_on; sleep 10; echo 0 > $T/tracing_on
cat $T/per_cpu/cpu2/trace > trace.2
```

A clean ten seconds of a single spinning task is the switch onto the core
at the start and nothing after. Add `workqueue/workqueue_execute_start`,
`timer/hrtimer_expire_entry` and `irq/softirq_entry` to name what ran.
`tick_stop` with `success=0` names the dependency that kept the tick:
`SCHED` (more than one runnable task), `POSIX_TIMER`, `PERF_EVENTS`,
`CLOCK_UNSTABLE`, `RCU`, `RCU_EXP`.

Turn every event off afterwards; a forgotten tracepoint is a permanent
cost.

## rtla

Ships with the kernel tree (`tools/tracing/rtla`); packaged as `rtla`.

```sh
rtla osnoise top -c 2-5 -d 60s           # per-CPU noise summary
rtla osnoise hist -c 2 -d 60s            # histogram of single-noise durations
rtla osnoise top -c 2 -s 50 -t           # stop at a 50 us noise, save the trace
rtla timerlat top -c 2 -d 60s            # wake-up latency: IRQ and thread
rtla hwnoise -c 2 -d 60s                 # interrupts off: hardware only
```

- osnoise columns: runtime per period, noise total, percentage of CPU
  available, the largest single noise, then counts for hardware, NMI,
  interrupt, softirq and thread interference. Hardware counts on a VM are
  the hypervisor.
- The osnoise thread is a task on the core. Run it where the workload
  will run, before the workload starts.
- With a stop threshold the saved trace ends at the event that caused the
  stall: who ran, which interrupt, for how long.
- timerlat reports the latency at the timer interrupt and at the thread
  it wakes; the difference is scheduling.

## Scheduling and syscalls

```sh
perf sched record -C 2 -- sleep 10 && perf sched timehist   # delay per wake-up
perf trace -t $TID -s -- sleep 10                           # syscall summary for a thread
strace -c -f -p $PID                                        # the same, heavier
```

A spinning loop's syscall summary should hold only what its design names:
the socket read and write, nothing else.

## Hardware

```sh
turbostat --quiet --interval 5 --num_iterations 2     # frequency, idle residency, SMI count
grep -E '^cpu' /proc/stat                              # eighth figure: steal
```

## Where the clock comes from

```sh
cat /sys/devices/system/clocksource/clocksource0/current_clocksource
dmesg | grep -i -E 'clocksource|tsc'
```

## Sources

`Documentation/admin-guide/cpu-isolation.rst` (the trace procedure and
expected output), `Documentation/trace/osnoise-tracer.rst`,
`Documentation/trace/timerlat-tracer.rst`, `Documentation/tools/rtla/`,
`Documentation/scheduler/sched-stats.rst`, `Documentation/filesystems/proc.rst`,
`include/trace/events/timer.h` (the `tick_stop` dependencies).
