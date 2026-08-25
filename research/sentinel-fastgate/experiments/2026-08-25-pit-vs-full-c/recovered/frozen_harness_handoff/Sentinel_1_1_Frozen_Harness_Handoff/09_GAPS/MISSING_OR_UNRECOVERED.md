# Missing / unrecovered artifacts

## 1. Security-level damaged/green breadth classifier — BLOCKING for faithful production Sentinel

Status: **NOT FOUND in the retained artifacts searched for this handoff.**

What is retained:
- Complete daily aggregate `damaged` / `green` breadth tape.
- Sentinel 1.1 exact daily oracle containing `damaged` and `green`.
- Position-level research scripts that reconstruct holding-day state (`own_dd`, momentum horizons, etc.) and later consume `green` / `red` classifications.

What is not retained/located:
- The original function/script that assigned each security-level holding to damaged/green (or green/red/amber) before aggregation.

Required behavior:
- Do **not** reverse engineer and silently call it certified.
- Search any older notebooks/temp files/source archives if they become available.
- If a candidate classifier is reconstructed, it must reproduce the frozen breadth tape before it can be accepted.

## 2. Full monolithic original interactive Python session
The ChatGPT research work persisted many result bundles and source fragments, but not every ephemeral notebook cell/script appears as a standalone library file. The package therefore distinguishes original retained source from derived oracle outputs.

## 3. Production share-level execution equivalence
The research Sentinel overlay is scalar. A real broker implementation must project shadow target holdings into actual integer-share orders, handle no-print legs and pending orders, and persist target vs realized exposure. That production execution layer is new work and should be certified separately from the controller oracle.
