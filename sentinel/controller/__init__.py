"""The Sentinel exposure controller: HOW MUCH of Wealth Core the account holds.

Never WHAT it holds. That is Wealth Core's, and the membrane between them is
one-directional — see `docs/sentinel-architecture.md` §1.

```text
sentinel/controller/frozen_rule.py   the native Sentinel thresholds, digest-verified
sentinel/controller/machine.py       the native Sentinel pure state machine
sentinel/controller/ldrc.py          authoritative optional Concordance LD-RC overlay
```

`ldrc.py` is retained strategy source, not implicit activation authority. Native
Sentinel remains independently auditable and the LD-RC overlay must pass its own
causal/certification gates before production use.
"""
