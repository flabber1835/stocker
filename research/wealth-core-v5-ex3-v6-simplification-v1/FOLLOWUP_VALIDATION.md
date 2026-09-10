# Follow-up prelaunch validation

User authorized one additional candidate replay after the ten-arm matrix completed.

- `python research/wealth-core-v5-ex3-v6-simplification-v1/test_followup.py`: 3 tests passed. Includes 20,000 composed Native/EX3 state comparisons against ramp10 and no_spy_rebound component behavior, all three exposure levels observed, bounded counters, selective peer AST identity, candidate-only budget and baseline-checksum tampering/missing-checksum falsifiers.
- Python compilation passed for candidate_followup.py, report_followup.py and test_followup.py. The generated replay driver also compiles and is derived from the SHA-pinned original driver using six exact source seams.
- Workflow structure passed: exactly one candidate job, baseline download pinned to run 34436432038, new one-slot ledger, dedicated FOLLOWUP_LAUNCH.json trigger. The previous ten-slot workflow is unchanged.
- Economic data and baseline results are validated in CI before the new budget reference is claimed. CI repeats the original eight preflight tests and three follow-up tests using the frozen runtime dependencies.

Full-PIT combined performance remains pending. Local preparation consumed zero additional replay slots.
