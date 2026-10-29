# Manual primary-path failure and recovery

Use only the dedicated, synthetic `dual-wan` scenario. This is an experiment guide;
the [2026-10-29 validation](live-validation.md) records one successful execution.
Automatic fault injection is not a shipped feature.

## Establish the baseline

Run `nlf verify build/my-dual-wan` and require a complete pass. On `branch`, inspect:

```text
show ip route 198.19.0.4
traceroute 198.19.0.4 source Loopback0
```

With the supplied costs, the intended preferred next hop is `198.18.0.2` via Gi0/1.
Confirm this observation before testing a failure. Forwarding decisions are not
inferred solely from the configuration file.

## Interrupt the primary access link

Keep a separate EVE console session available for recovery. On `branch`:

```text
configure terminal
interface GigabitEthernet0/1
 shutdown
end
```

Do not save this temporary fault to startup-config. After convergence, inspect the
route to `198.19.0.4` again. The intended alternative next hop is `198.18.0.10` via Gi0/2.
Probe the headquarters loopback from the branch loopback:

```text
ping 198.19.0.4 source Loopback0 repeat 5 timeout 1
```

The normal `nlf verify` baseline intentionally still expects all original neighbors.
During this fault it should report missing FULL adjacencies; it must not produce an
overall green result simply because an alternate path exists. Use raw ping and route
evidence to assess continuity during the fault.

## Always restore

Whether the alternate path worked or failed, return to the branch console:

```text
configure terminal
interface GigabitEthernet0/1
 no shutdown
end
```

Wait for adjacencies to settle and run a new `nlf verify` baseline. Confirm the primary
next hop is restored. If the terminal session was lost, use the EVE console to recover.

No convergence-time claim can be derived from this procedure alone. A timed experiment
requires continuous probes, timestamps, a defined failure event and repeat runs.
