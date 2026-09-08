# Median-5 / Caesar 20 slot-capacity forensics

This branch is diagnostic only.

It replays the exact certified Median-5 full-PIT path and adds observer-only telemetry for:

- entry reservation size versus nominal 5% target,
- actual open fill size versus nominal target,
- LLYVK and RCUS slot state,
- sell signals, sell attempts, and sell fills,
- candidate availability when either suspicious slot is treated as free for observation only,
- prevalence of underfilled entries across the entire 20-year path.

The forensic workflow hard-asserts byte-for-byte SHA-256 equality of `engine/daily.csv` and `engine/summary.json` against successful certified end-book run 34171595204. Any economic-path change therefore fails the forensic run.

No production, strategy, corpus, classifier, or certified source is modified.