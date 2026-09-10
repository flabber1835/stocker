# Prelaunch validation

Date: 2026-09-10. Full-PIT slots consumed during local preparation: **0**.

Commands:

```bash
python research/wealth-core-v5-ex3-v6-simplification-v1/preflight.py
python -m py_compile research/wealth-core-v5-ex3-v6-simplification-v1/*.py
```

Result: **8 tests passed**, 5.231 seconds on the local runner. Compilation passed. Local NumPy 2.4.6 / pandas 3.0.5; this is synthetic preflight evidence. Economic replay uses Python 3.12.14 and the frozen runtime's hash-locked dependency closure. CI repeats preflight in that environment before consuming any slot.

Coverage:

- All ten sources compile; baseline is byte-identical to the SHA-pinned oracle.
- A deliberate Core slot-count mutation fails the controller-only AST guard.
- 20,000 seeded and sequential Native/EX3 state comparisons produce identical decisions for bounded counters. Native outputs 0/55/65/100 all observed.
- 300 randomized held-book peer comparisons, missing residual histories, nonfinite observations, identical-series ties, and settled red holdings retained as neighbors. Selective evaluation preserves breadth while reducing pair calculations.
- One-stage 10/20-close ramps exercise prior-close threshold-check timing and unhealthy-streak reset.
- Mapping 65% output to 55% preserves original internal state.
- Cross-surface and rebound release ablations are distinguished from baseline by targeted observations.
- A reused budget-reference refusal makes exactly one request and propagates failure; an eleventh arm cannot claim a slot.
- Economic-screen boundaries reject both excessive gains and losses; missing all artifacts produces INCOMPLETE and no passes.

Workflow structure check passed: exactly one baseline plus nine dependent treatment arms; only LAUNCH.json changes trigger this research workflow; checkout credentials are not persisted. Budget mutation is isolated to a GitHub ref claim immediately before the replay call. The summary job has issue-comment permission and read-only repository contents.

Initial preflight exposed a test-generator `float(None)` error. It was corrected to retain missing observations before all eight tests passed. No economic replay was started during this correction.

This validates the harness and intended transformations. Historical parity and economic preservation remain pending full-PIT results.
