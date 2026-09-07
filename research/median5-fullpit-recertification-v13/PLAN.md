# Median-5 full-PIT recertification v13

Objective: run one fresh canonical 20-year Median-5 replay and certify its output provenance and economics.

## Frozen economic definition

- 20 slots
- 5% entry weight
- Median-5 top-3 admission hardening using the trailing five causal rank-order observations
- exact one-session dividend settlement
- `COOLDOWN = 21`
- `REVIEW_AGE = 119`
- `STOP_RET = 0.70`
- `COST = 0.001`
- `MIN_ADV20 = 20_000_000.0`
- `MIN_DAY_DV = 5_000_000.0`

No adversarial perturbation is applied.

## Full-PIT requirements

The run must prove:

- replay mode is `fullpit`
- exact certified corrected base normalized AST identity
- immutable canonical PIT dataset hash
- exact frozen classifier source
- exact frozen runtime source
- exact one-session dividend lag
- no prerecorded decisions
- 5,032 measurement sessions from 2006-07-31 through 2026-07-31
- strict security-type traversal and candidate coverage equal the corrected certified baseline
- no classification expansion required

## Certification output

Preserve the complete engine output, generated source, package-integrity evidence, classifier validation, preflight source evidence, run log, and machine-readable `RESULT.json` as a GitHub Actions artifact.

A certification report is created only after the fresh run completes and its artifact is independently inspected.
