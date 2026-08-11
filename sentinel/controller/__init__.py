"""The Sentinel exposure controller: HOW MUCH of Wealth Core the account holds.

Never WHAT it holds. That is Wealth Core's, and the membrane between them is
one-directional — see `docs/sentinel-architecture.md` §1.

```text
sentinel/controller/frozen_rule.py   the thresholds, LOADED and digest-verified
sentinel/controller/machine.py       the pure state machine
```
"""
