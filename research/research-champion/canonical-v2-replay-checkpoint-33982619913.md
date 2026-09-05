# Research Champion canonical v2 replay checkpoint

## Verified admission checkpoint

- Branch: `research/research-champion`
- Frozen profile: `strategy9-e3-research-champion-v1`
- Canonical reconstruction run: `33982619913`
- Reconstruction source: `8bb1e499f2a96a58959bf91def1b149ba573e6a6`
- Admission pointer commit: `548bcee34cd7200e7638ec0af922896a715283a4`
- Pointer: `backtester/data/canonical-pit-20y.json`
- Dataset hash: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- Manifest SHA-256: `cfa94043084c1cbd83230b5a7225baa45b526797db4581c192561e0fb82ab5b0`
- Package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c`
- Pinned runtime: `887f479b15ad861313da666ad698034d3847121c`
- Reconstruction evidence artifact ID: `9975239307`
- Reconstruction evidence archive digest: `sha256:7ff531f997ce4551fdf3b0239b089eb73a61d55b51d427ea090d8e6d396496c6`

The reconstruction run completed successfully at 2026-09-05T19:09:52Z. Build, validation, publication, pointer pinning, and evidence upload all succeeded. The build workflow explicitly enforced dataset schema `backtester.canonical-pit-dataset/2`, manifest status `PASS`, and exact reconstruction-source identity before publication.

## Replay activation

At this checkpoint, GitHub reported zero workflow runs for the admission pointer commit. This documentation-only commit activates the existing Champion branch push workflows using the admitted package. The canonical builder is path-filtered to its own workflow file, which this commit leaves unchanged.

Champion source, parameters, runtime authority, promotion assertions, dataset pointer, and all PIT/financial gates remain unchanged. The replay must execute `backtester/run_research_champion_strict_pit_20y.py --mode fullpit` for warmup 2006-01-03, measurement start 2006-07-31, and end 2026-07-31.

## Certification state at activation

Full Champion replay and the common finalizer are pending. This checkpoint is an operational record. The repository's common PIT certification finalizer remains the sole authority for the final certification result.
