# Bounded decision comparison — 2026-09-19

PASS, conditional on the retained historical inputs. Production revision:
`daa43caf995779bfa7e67195785520744021cb45`. Reference: GitHub Actions run
[34544522249](https://github.com/flabber1835/stocker/actions/runs/34544522249),
artifact `10179195109`, `champion-certification-20y-and-pit-weights`.
Every retained artifact member was verified against its SHA256 manifest;
observations and expected decisions have separate source pins in the runner.
The reference result matches the repository's retained result byte for byte.

- 5,176 observed sessions, including 5,032 measured sessions from 2006-07-31
  through 2026-07-31: zero native-target, recovery-target/reason, effective
  exposure or severe-signal mismatches. All 23 exposure changes retain dates.
- 17 controller JSON restoration boundaries: zero subsequent mismatches.
- 40,687 dated V5 admission/skip cases and 416 opening-quantity cases:
  zero decision/quantity mismatches given the recorded candidates and economics.
- Exact budget arithmetic changes 142 numeric values by at most
  `$0.000000000014551915228366852`. None changes an admission or the opening
  quantity in these recorded cases. This is not identical floating-point output.
- Opening quantities satisfy independent 80-digit decimal cost bounds.
  Intentionally oversized quantities fail those bounds; an intentionally wrong
  expected exposure is detected by the decision comparator.
- Final computation: 5.22 seconds, container without network, 1 GiB limit,
  two CPUs. A preliminary host-mounted run was stopped during harness preparation;
  only the final, unchanged container-local copy supplies these results.

The existing research result is 56.26534933655832x, 22.323600023175572% CAGR,
and -26.52803738241426% maximum drawdown. These are retained research metrics,
not newly computed production performance. Its classification overlay, initial
book and input economics differ from the provisional fresh-account experiment.
Controller observations, candidate ranking, prices and cash are supplied as
historical inputs here. We did not reconstruct rankings, stock holdings, stops,
terminal events, breadth, leadership or NAV. Conditional agreement cannot show
that today's full system produces the same inputs, trades or returns.

The larger replay remains deferred at the owner's request. Its corrected first
attempt refused on 2006-09-18 after 34 completed sessions because RSAS cash-merger
terms are absent. No input repair or strategy change was made for this smoke test.

## Reproduce

Retrieve the reference artifact with authenticated GitHub CLI, writing its binary
stdout to a ZIP, and extract it as `/reference`. Stage the unchanged checkout
inside `sentinel-test:ci` rather than repeatedly reading configuration through
a Windows bind mount. The Docker invocation uses `--entrypoint python`,
`--network none --memory 1g --cpus 2`. Copy `sentinel`, `shared`,
`research/provisional_20y`, `tests/champion`, and
`docs/sentinel-handoff/00_README` into `/tmp/smoke`, then run:

```sh
PYTHONPATH=/tmp/smoke:/tmp/smoke/shared python -m research.provisional_20y.decision_smoke --reference /tmp/reference --output /out/decision-smoke-final
```

The original artifact download command was:

```sh
gh api repos/flabber1835/stocker/actions/artifacts/10179195109/zip
```

`result.json` records counts, timing, source identities and scope. The exposure
transition file records all changed effective exposure dates and same-day close
decisions. Full generated decisions and opening quantities remain under
`C:/GitHub/stocker/.codex-tmp/provisional-20y-evidence/decision-smoke-final`;
`local-output-sha256.json` commits their bytes. The runner regenerates them.
