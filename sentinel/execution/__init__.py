"""Sentinel's execution layer — the membrane between a decision and a share.

```text
DETERMINISTIC                          MESSY
Wealth Core shadow                     broker
Sentinel controller                    fills, outages, halts, rejects
target exposure    ─────────────→      commands
```

Everything above this package is reproducible from a snapshot and a pinned
corpus. Everything this package talks to is not. The contract in
`docs/sentinel-execution-contract.md` exists because Stocker's execution lineage
failed in four ways that were all the same omission — no durable deterministic
identity for a side effect, and no state meaning "we do not know" — so every
recovery path had to guess, and each guess could duplicate or abandon a real
order.

Module map:

```text
identity.py   the derived client key. Recomputable from durable state alone
states.py     the command state machine, and the runtime permission kernel
contract.py   the typed broker port, and capabilities that fail closed
commands.py   commands, remaining-delta arithmetic, dust, authorisation
```

Nothing here imports a Stocker service, and nothing here decides WHAT to hold.
"""

# Package-level policy is intentional: every supported execution entry point
# imports ``sentinel.execution`` before it can reach reconciliation. Install the
# fail-closed stale-restore ownership rule once at the common membrane so CLI,
# automation and recovery tools cannot diverge on whether a bare ``sntl-``
# prefix constitutes ownership authority.
from sentinel.execution import recovered_order_policy as _recovered_order_policy

_recovered_order_policy.install()

# Alpaca's strict terminal-recovery witness is the point at which a COMPLETE
# observation can become durable negative-space authority. Bind that point to
# the takeover fence too. This import is deliberate: broker-capable execution
# already depends on the concrete Alpaca certification boundary, and the guard
# must be installed before any caller can obtain its strict_advance function.
if _recovered_order_policy.strict_enabled():
    from sentinel.execution import alpaca as _alpaca

    _recovered_order_policy.install_alpaca_restore_guard(_alpaca)
    del _alpaca

del _recovered_order_policy
