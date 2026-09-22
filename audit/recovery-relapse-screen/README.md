# Entered recovery risk: rejection evidence

Both the original bridge and the sign-confirmed bridge fail the fixed research
risk screen. No twenty-year continuation was started. See
`docs/recovery-relapse-screen.md` for economic interpretation and all remaining
limitations. Registration: `d09c7394`; verified base:
`ee23c894c97a2c4023654ce3a56a62728f5b061e`.

`summary.json` records eight paths, immutable input/source hashes, retained
control parity, restart counts and each candidate's verdict. The eight gzip
files retain every observation, opening trade, before/after account state,
controller state and price. `independent-audit.json` reconstructs prices and
separately attributes old ownership's overnight losses versus post-trade
intraday P&L. `tests.xml`, `mutations.json` and `ownership.json` retain checks.
Research tests are explicitly run locally; the repository ownership validator
covers its declared permanent roots and is not proof of CI running these tests.

The immutable PR #438 sources are loaded from Git object
`3c98d99aeb3646ff0883bdf2c76221492ef9b3bb`, with its pinned #433 and #437 helpers
and owned-impairment parent. None of those branches or artifacts was edited.
Reproduction requires those Git objects, Python 3.12 and the existing research
dependencies (NumPy, calendar and production dependencies).

Exact commands from this feature worktree:

```powershell
$py = 'C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe'
$env:PYTHONPATH = "$PWD;$PWD/shared"
& $py -m research.recovery_stress.run --output audit/recovery-relapse-screen
& $py -m research.recovery_stress.audit audit/recovery-relapse-screen
& $py -m pytest research/recovery_stress/test_recovery.py -q -p no:cacheprovider --basetemp=C:/GitHub/stocker/.codex-tmp/recovery-stress-tests-final --junitxml=audit/recovery-relapse-screen/tests.xml
& $py -m research.recovery_stress.mutations
& $py -m compileall -q research/recovery_stress
& $py tools/validate_test_responsibility.py --base ee23c894c97a2c4023654ce3a56a62728f5b061e --output audit/recovery-relapse-screen/ownership.json
git diff --cached --check
```

For another reproduction, use a new output directory: the runner refuses to
overwrite even a partial output. No NAS or broker was accessed. No signal
thresholds, policy parameters, generated shocks or acceptance budgets were
changed after results. A final hand-worked liquidation/overnight-loss test was
added after the panel; executed-source retention distinguishes this added
validation from the unchanged code that generated the economic results.
