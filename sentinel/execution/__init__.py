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

# Install the explicit broker-boundary hardening before callers import concrete
# execution adapters. The second layer scopes new invariants to production
# reconciliation and real instrument-identity adapters so low-level test helpers
# do not acquire authority they never claimed.
from sentinel.execution.alpaca_remediation import install as _install_alpaca_remediation
from sentinel.execution.alpaca_remediation_compat import install as _install_compat

_install_alpaca_remediation()
_install_compat()
del _install_alpaca_remediation
del _install_compat
