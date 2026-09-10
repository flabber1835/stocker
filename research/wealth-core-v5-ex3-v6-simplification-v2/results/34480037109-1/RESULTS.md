# Simplification round 2 results

Status: **COMPLETE**. [Run 34480037109](https://github.com/flabber1835/stocker/actions/runs/34480037109). Source `5dfcdd4135d3f5a98ff923a3d0be62f147cacc2b`.

Ten replay starts maximum. Slot claims are permanent repository refs under `research-budget/simplification-v2/slot-*`. Failed starts remain charged. Artifact claims below count retained evidence; repository refs are the budget authority.

Claims represented in artifacts: 10/10. Missing or failed arms: none.

| Arm | Preservation | 20y CAGR | 20y max DD | 20y multiple | Changed allocation sessions | Max NAV path difference |
|---|---|---:|---:|---:|---:|---:|
| baseline | PASS | 21.8332% | -27.3562% | 51.9214 | 0 | 0.000% |
| cleanup_state | PASS | 21.8332% | -27.3562% | 51.9214 | 0 | 0.000% |
| symmetric_peers | PASS | 21.8332% | -27.3562% | 51.9214 | 0 | 0.000% |
| clean_cached | PASS | 21.8332% | -27.3562% | 51.9214 | 0 | 0.000% |
| no_peers | FAIL | 21.4825% | -27.3562% | 49.0129 | 142 | 7.789% |
| fixed_ramp10 | FAIL | 20.3491% | -30.8146% | 40.6339 | 262 | 22.395% |
| persistence_only | FAIL | 21.2229% | -27.3562% | 46.9597 | 33 | 10.810% |
| no_peers_fixed_ramp | FAIL | 20.4997% | -30.8146% | 41.6630 | 341 | 20.429% |
| no_peers_persistence | FAIL | 21.0720% | -27.3562% | 45.8046 | 162 | 13.004% |
| minimal_recovery | FAIL | 20.5123% | -30.8146% | 41.7504 | 347 | 20.262% |

## All-window deltas against the simplified candidate

Pass requires every window: absolute CAGR delta <= 0.25 pp/year, drawdown deterioration <= 1 pp, absolute terminal-multiple change <= 5%. Higher returns beyond the symmetric preservation limit fail.

| Arm | Window | CAGR delta (pp) | Max DD delta (pp; positive improves) | Multiple change | Pass |
|---|---|---:|---:|---:|---|
| baseline | 5y | +0.0000 | +0.0000 | +0.000% | True |
| baseline | 10y | +0.0000 | +0.0000 | +0.000% | True |
| baseline | 15y | +0.0000 | +0.0000 | +0.000% | True |
| baseline | 20y | +0.0000 | +0.0000 | +0.000% | True |
| cleanup_state | 5y | +0.0000 | +0.0000 | +0.000% | True |
| cleanup_state | 10y | +0.0000 | +0.0000 | +0.000% | True |
| cleanup_state | 15y | +0.0000 | +0.0000 | +0.000% | True |
| cleanup_state | 20y | +0.0000 | +0.0000 | +0.000% | True |
| symmetric_peers | 5y | +0.0000 | +0.0000 | +0.000% | True |
| symmetric_peers | 10y | +0.0000 | +0.0000 | +0.000% | True |
| symmetric_peers | 15y | +0.0000 | +0.0000 | +0.000% | True |
| symmetric_peers | 20y | +0.0000 | +0.0000 | +0.000% | True |
| clean_cached | 5y | +0.0000 | +0.0000 | +0.000% | True |
| clean_cached | 10y | +0.0000 | +0.0000 | +0.000% | True |
| clean_cached | 15y | +0.0000 | +0.0000 | +0.000% | True |
| clean_cached | 20y | +0.0000 | +0.0000 | +0.000% | True |
| no_peers | 5y | -0.0000 | +0.0000 | -0.000% | True |
| no_peers | 10y | +0.0638 | -0.0000 | +0.505% | True |
| no_peers | 15y | -0.5055 | -0.0000 | -6.020% | False |
| no_peers | 20y | -0.3507 | -0.0000 | -5.602% | False |
| fixed_ramp10 | 5y | -1.2737 | -3.7897 | -4.761% | False |
| fixed_ramp10 | 10y | -0.8699 | -3.4584 | -6.657% | False |
| fixed_ramp10 | 15y | -1.6317 | -3.4584 | -18.238% | False |
| fixed_ramp10 | 20y | -1.4841 | -3.4584 | -21.740% | False |
| persistence_only | 5y | +0.0000 | -0.0000 | -0.000% | True |
| persistence_only | 10y | -1.1219 | -0.0000 | -8.509% | False |
| persistence_only | 15y | -0.9839 | -0.0000 | -11.404% | False |
| persistence_only | 20y | -0.6103 | -0.0000 | -9.556% | False |
| no_peers_fixed_ramp | 5y | -1.2737 | -3.7897 | -4.761% | False |
| no_peers_fixed_ramp | 10y | -0.8281 | -3.4584 | -6.347% | False |
| no_peers_fixed_ramp | 15y | -1.4234 | -3.4584 | -16.096% | False |
| no_peers_fixed_ramp | 20y | -1.3335 | -3.4584 | -19.758% | False |
| no_peers_persistence | 5y | +0.0000 | -0.0000 | +0.000% | True |
| no_peers_persistence | 10y | -1.0513 | -0.0000 | -7.994% | False |
| no_peers_persistence | 15y | -1.2212 | -0.0000 | -13.967% | False |
| no_peers_persistence | 20y | -0.7612 | -0.0000 | -11.781% | False |
| minimal_recovery | 5y | -1.2737 | -3.7897 | -4.761% | False |
| minimal_recovery | 10y | -0.9146 | -3.4584 | -6.988% | False |
| minimal_recovery | 15y | -1.4788 | -3.4584 | -16.670% | False |
| minimal_recovery | 20y | -1.3209 | -3.4584 | -19.589% | False |

Full JSON includes runtime, peer work counts, turnover, tail returns, underwater durations and fixed crisis windows. Per-arm artifacts retain daily tapes, Core parity evidence, generated sources and logs for 90 days. Screening is historical evidence; production implementation and certification require separate review.

## Original V5/V6 comparison

The table above screens against the simplified candidate. Original-strategy preservation is reported separately below. The stored candidate already exceeds the original symmetric CAGR tolerance. Both criteria retain their preregistered thresholds.

| Arm | Simplified-candidate screen | Original V5/V6 screen |
|---|---|---|
| baseline | PASS_PRESERVATION_SCREEN | FAIL_PRESERVATION_SCREEN |
| cleanup_state | PASS_PRESERVATION_SCREEN | FAIL_PRESERVATION_SCREEN |
| symmetric_peers | PASS_PRESERVATION_SCREEN | FAIL_PRESERVATION_SCREEN |
| clean_cached | PASS_PRESERVATION_SCREEN | FAIL_PRESERVATION_SCREEN |
| no_peers | FAIL_PRESERVATION_SCREEN | FAIL_PRESERVATION_SCREEN |
| fixed_ramp10 | FAIL_PRESERVATION_SCREEN | FAIL_PRESERVATION_SCREEN |
| persistence_only | FAIL_PRESERVATION_SCREEN | FAIL_PRESERVATION_SCREEN |
| no_peers_fixed_ramp | FAIL_PRESERVATION_SCREEN | FAIL_PRESERVATION_SCREEN |
| no_peers_persistence | FAIL_PRESERVATION_SCREEN | FAIL_PRESERVATION_SCREEN |
| minimal_recovery | FAIL_PRESERVATION_SCREEN | FAIL_PRESERVATION_SCREEN |

Complete original-comparator window deltas are retained in SUMMARY.json.

## Stored generated source

- [baseline](sources/baseline.py)
- [cleanup_state](sources/cleanup_state.py)
- [symmetric_peers](sources/symmetric_peers.py)
- [clean_cached](sources/clean_cached.py)
- [no_peers](sources/no_peers.py)
- [fixed_ramp10](sources/fixed_ramp10.py)
- [persistence_only](sources/persistence_only.py)
- [no_peers_fixed_ramp](sources/no_peers_fixed_ramp.py)
- [no_peers_persistence](sources/no_peers_persistence.py)
- [minimal_recovery](sources/minimal_recovery.py)
