# Stored simplified strategy source

`simplified_candidate.py` contains the complete generated research strategy from the successfully completed combined-candidate replay, including the frozen Core book and the composed controller. SHA256: `26b99f4a5f7fefc9d295479cc604e85a761db64cc5416664145fdd1b94b72939`.

This is byte-identical to the generated source reported by [run 34441488484](https://github.com/flabber1835/stocker/actions/runs/34441488484), job 102757271609, at source head `8d03d04c0787ddd9b1bed7ecef58183f22288a47`. `SIMPLIFIED_CANDIDATE_MANIFEST.json` preserves its exact result and lineage.

Composition: selective peers, bounded counters, one 55% recovery stage requiring ten healthy closes, and removal of the SPY rebound release. Cross-surface recovery remains active. Allocations: 0%, 55%, 100%.

20y CAGR 21.833176632696083%; maximum drawdown -27.35619982948002%; ending multiple 51.92142251352529. The original preservation-screen verdict remains FAIL because the 20y CAGR gain exceeds the symmetric 0.25 pp limit. Source preservation does not promote the candidate to production.

Run this source through the pinned research driver and workflow: it requires the frozen runtime dependencies, certified-source working directory and canonical full-PIT dataset. Its inherited header describes an older non-PIT ancestor; the workflow's enforced full-PIT mode and verified data/source hashes identify the completed experiment. The original bytes are retained for reproducibility.
