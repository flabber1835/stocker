# Frozen recovery bridge synthetic experiment

Registration: commit `48da5169`, before policy implementation and panel results.
Base: `ee23c894c97a2c4023654ce3a56a62728f5b061e`.
Design and interpretation: `docs/owned-recovery-bridge.md`.

This directory retains every one of the 26 cases: 13 predetermined synthetic
price paths at two formation ages. Each compressed file includes 120 daily
observations, controller decisions, account holdings/cash, signed opening
trades, fees and closing NAV. No golden artifact was replaced. `summary.json`
binds the traces and helper sources by SHA256 and records the frozen numerical
screen. `independent-audit.json` independently reconstructs prices, account cash,
shares and daily P&L and reports retained Core/controller parity and the account
model sensitivity. `tests.xml`, `mutations.json` and `ownership.json` retain
local validation. The repository ownership validator covers its declared
permanent test roots; the research suite here is explicitly run locally and
is not silently claimed to have a CI execution owner.

The helpers are loaded from immutable Git objects, not editable neighboring
worktrees. Reproduction requires Git objects for:

- PR #433: `f2a50c7b6ff4c9686f49b6eb53863e8e2b9959bb`.
- Owned impairment parent: `7250ce3d65cc38a103989d460fe3c557a38343c8`.
- PR #437 Owned55: `181dfef1682b1351fe715059dd5ad99329321f5a`.
- Prior phase evidence: `b446e7e02f7257c17c4c57cd1c74eefcd1243303`.

From the feature worktree, commands used:

```powershell
$py = 'C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe'
$env:PYTHONPATH = "$PWD;$PWD/shared"
& $py -m research.recovery_bridge.run --output audit/owned-recovery-bridge
& $py -m research.recovery_bridge.audit audit/owned-recovery-bridge
& $py -m pytest research/recovery_bridge/test_model.py -q -p no:cacheprovider --basetemp=C:/GitHub/stocker/.codex-tmp/recovery-bridge-tests-final --junitxml=audit/owned-recovery-bridge/tests.xml
& $py -m research.recovery_bridge.mutations
& $py -m compileall -q research/recovery_bridge
& $py tools/validate_test_responsibility.py --base ee23c894c97a2c4023654ce3a56a62728f5b061e --output audit/owned-recovery-bridge/ownership.json
git diff --check
```

Use a **new output directory** for reproduction; the runner refuses a completed
output. No new twenty-year experiment, paper activation or economic
certification follows automatically from this numerical screen.
