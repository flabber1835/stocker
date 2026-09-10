# Round 2 prelaunch validation

The standalone simplified candidate source is stored in the preceding snapshot commit. Its SHA256 matches the completed follow-up replay: `26b99f4a5f7fefc9d295479cc604e85a761db64cc5416664145fdd1b94b72939`.

Commands:

```bash
python research/wealth-core-v5-ex3-v6-simplification-v2/preflight_round2.py
python -m py_compile research/wealth-core-v5-ex3-v6-simplification-v2/*.py
```

Result: **8 tests passed in 8.043 seconds**. All ten generated strategy sources and the generated replay driver compile. Workflow parsing confirms one baseline plus nine gated treatments, the exact prior candidate run for reference download, and the dedicated round-2 launch trigger.

Evidence:

- 20,000 synthetic observations compare all three exact arms against the stored candidate; Native outputs, CandidateA allocations and reason paths match. Periodic snapshot restoration is included.
- All ten arms pass 1,000-observation same-version snapshot/restart equivalence checks.
- Peer tests cover 300 randomized held books, missing and constant histories, tied series, .145 threshold ties, pair symmetry and cache reset between sessions. A complete 20-holding unresolved cohort reduces pair evaluations from 380 to 190 with identical breadth.
- Targeted falsifiers distinguish peer removal, forced ramp entry after non-fragile recovery and deletion of cross-surface release. Recovery counting retains the prior-close check.
- A Core cash mutation fails the AST scope guard. Removed ramp/streak/history fields and dead rebound branches are checked directly.
- Duplicate slot refusal makes one request and propagates failure; an eleventh arm cannot claim a slot. Artifact tampering and missing checksums fail before replay.
- Summary validation rejects modified generated source even when its file checksum is internally consistent. The separate comparator test retains the stored candidate's failure against original V5/V6.
- Permanent publication preserves the observed branch parent and uses a non-force update. API operations are mocked during this test; no budget or repository mutations occur.

Preparation found and corrected an overcount in the expected obsolete ramp-index source seam (three residual assignments after removing the ramp block). No full-PIT replay had started. No strategy threshold or acceptance threshold changed.

CI runs the original eight tests, three follow-up tests and these eight tests with the pinned runtime dependency closure before any replay claim. Historical parity and economics remain pending the new ten-slot run.
