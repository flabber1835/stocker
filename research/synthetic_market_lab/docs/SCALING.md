# Synthetic Market Lab v1 — Scaling Plan

## Target shape

The architecture scales by world because independent seeds have no cross-world state. A mature 5,000-security, 20-year world has up to roughly 25.2 million security-day rows. One hundred such worlds can therefore exceed 2.5 billion security-day rows, so generation and storage must be partitioned.

## Parallel generation

`world_id = SHA256(generator_version + canonical configuration + seed)` is the immutable unit of work. A coordinator can submit each world independently to local processes, GitHub runners, or batch infrastructure. No result from one world is an input to another. Named RNG streams keep subsystem draws stable within each world.

Macro/factor/sector paths remain small in memory. Company state is vectorized by NumPy. Price/universe emission is streamed by time, as Phase 1 already does for the two largest public tables.

## Storage evolution

Phase 1 uses canonical gzip/CSV for transparent byte-level replay. Scale-out should introduce a pinned Arrow/Parquet serialization contract with fixed schema, row-group policy, codec/version, metadata ordering, and canonical partition names. Recommended partitions are `world_id/year` for prices/universe and `world_id/table` for smaller event tables. Ground truth and public data remain separate artifact namespaces.

## Immutable publication

Every published world records validated configuration, generator version, environment identity, named RNG-stream seeds, per-file hashes, validation result, and world hash. Regeneration of an existing world ID must reproduce the same file hashes or fail certification.

## GitHub and local execution

CI should run the small adversarial fixture and deterministic property tests. The 200-company reference world belongs in an explicit research workflow or local reproduction job. Large 3,000–5,000-security worlds should be external immutable artifacts, with manifests and references committed to Git.

A future workflow can matrix over seeds/configs, generate worlds in parallel, validate each independently, and publish only passing artifacts. Local execution uses the same CLI and configuration.

## Throughput optimizations

The next scale step is profiling-based: vectorize remaining per-security transitions, batch writes, replace repeated identity lookups with interval indices, and parallelize independent worlds. Event-level microstructure remains an optional later layer because it changes compute scale substantially.

## Cross-world diagnostics

Cross-world analysis consumes immutable world artifacts only after generator validation. Strategy results never feed generator calibration. Any economic-model change increments the generator version; old worlds remain immutable under their original IDs.
