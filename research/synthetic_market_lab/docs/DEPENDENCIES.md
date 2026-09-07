# Synthetic Market Lab v1 — Dependency Evaluation

Research date: 2026-09-07.

## Decision summary

Phase 1 adopts only a small deterministic numerical/schema stack. Large market-simulation and RL frameworks are not runtime dependencies.

| Project | Problem solved | Maintenance / license | Reproducibility & scale | Phase-1 decision |
|---|---|---|---|---|
| QuantEcon.py | Markov chains, state-space models, quantitative-economics primitives | Active 2026 releases; MIT | Strong mathematical primitives; deterministic when RNG is controlled | Concepts/reference only. The required finite-state regime transition is small and easier to audit locally. |
| ABIDES (original) | Agent-based discrete-event exchange simulation and realistic message/latency mechanics | Original release line is old; BSD-3-Clause | Strong event-level market microstructure; high complexity for 20-year daily multi-security worlds | Concepts only for future microstructure. |
| JPMorgan ABIDES successor (`abides-jpmc-public`) | Modular ABIDES Core/Markets/Gym successor | Public successor; permissive lineage | Better modularization, still an event-level simulator intended for exchange/agent research | Revisit when intraday/order-book modeling is authorized. |
| FinRL / FinRL-Meta | Data/environment/agent separation and RL market environments | Repository activity continues in 2026; MIT | Useful environment abstractions; centered on RL workflows and historical-data processors | Interface concepts only. No RL dependency. |
| Mesa | General Python agent-based modeling | Very active in 2026; Apache-2.0 | Good agent scheduling and extensibility; additional framework abstractions for a vectorizable company universe | No Phase-1 dependency. Revisit if heterogeneous autonomous economic agents become a requirement. |
| NumPy | Deterministic vectorized numerical generation | Mature, actively maintained; BSD-style | Excellent scale for 200 to several thousand companies; explicit RNG bit generators | Adopt and pin. |
| Pydantic | Typed configuration/schema validation | Actively maintained; MIT | Deterministic validation; negligible runtime impact at world scale | Adopt and pin. |
| PyArrow/Parquet | Columnar storage and efficient scans | Active, Apache-2.0 | Excellent large-world scale; serialized bytes can vary across library versions/settings | Deferred for Phase 1; candidate for scale-out after encoding is pinned/certified. |
| Polars | High-performance DataFrame/query engine | Very active; MIT | Excellent scale; unnecessary for the initial forward generator | Deferred. Useful for later cross-world diagnostics. |

## Detailed conclusions

### QuantEcon

Repository: https://github.com/QuantEcon/QuantEcon.py

QuantEcon is a credible source for Markov-chain/state-space concepts and remains actively maintained. Phase 1 only needs a transparent finite-state transition kernel plus continuous autoregressive macro state. Implementing those primitives locally keeps the causal equations visible in one small module and avoids coupling generator reproducibility to a larger numerical API.

Decision: use concepts and equations as reference; no runtime dependency.

### ABIDES / ABIDES concepts

Original repository: https://github.com/abides-sim/abides

Successor repository: https://github.com/jpmorganchase/abides-jpmc-public

ABIDES demonstrates realistic discrete-event exchange simulation, interacting agents, network latency, exchange protocols, order flow, and market-making. These are valuable for a future intraday execution/microstructure layer. Phase 1 operates on daily observations over ~20 years and thousands of eventual securities. Event-level order books would dominate complexity and compute while adding little to the requested first validation target.

Decision: preserve an explicit future execution/microstructure interface and adopt ABIDES concepts only when intraday/order-book behavior is authorized.

### FinRL / FinRL-Meta

Repositories:

- https://github.com/AI4Finance-Foundation/FinRL
- https://github.com/AI4Finance-Foundation/FinRL-Meta

The useful idea is separation of data, environment, and agent interfaces. The lab applies the same separation to true state, public state, and strategy-facing PIT state. FinRL's RL agents, Gym environments, historical data processors, and training stack are outside Phase-1 needs.

Decision: borrow the interface separation concept; no FinRL runtime dependency.

### Mesa

Repository: https://github.com/mesa/mesa

Mesa is actively maintained and well suited to heterogeneous agent-based simulations. The company layer here is primarily a large collection of state vectors driven by common causal processes. NumPy vectorization is simpler, faster, and easier to make byte-reproducible for this workload.

Decision: no Phase-1 dependency. Re-evaluate if later worlds require endogenous interactions among banks, households, firms, policymakers, or trading agents.

### NumPy

NumPy provides vectorized state evolution and a named deterministic RNG stream model. Phase 1 uses `PCG64DXSM`, one independently seeded stream per subsystem, and records the NumPy version in every world manifest.

Decision: required and pinned in the isolated lab requirements.

### Pydantic

Pydantic validates world configuration at the research boundary. It is not used in the inner daily loops. Canonical configuration serialization is derived from the validated model.

Decision: required and pinned in the isolated lab requirements.

### Storage libraries

Phase 1 uses canonical CSV + gzip with deterministic row/column ordering and gzip timestamp zero. This makes byte hashes simple to reason about and inspect. Large-scale worlds should use a pinned Arrow/Parquet encoding profile after a deterministic serialization contract is added.

## Reproducibility policy for all dependencies

A world manifest records Python, NumPy, Pydantic, generator version, validated configuration, seed, named RNG-stream derivation, and every output SHA-256. A dependency upgrade changes the generator compatibility identity until deterministic replay is re-certified.
