# Production-only 20-year replay: run 33352236633 runtime identity failure

## Classification

Harness invocation failure before the first historical session. No production strategy decision or portfolio state was evaluated.

## Frozen inputs

- Backtester branch: `research/backtester`
- Run head: `8b307b55ccfb220f2fa79fbfad96b38201999a9a`
- Pinned production source: `887f479b15ad861313da666ad698034d3847121c`
- Canonical PIT dataset hash: `f9fb220871ad4152549d31a5da6e0dbcdd327dc7b05843764511b0e800ddb19b`
- Canonical package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:4f53e51d8171aab8a8ac9df90e116d27b0f9b54f95629154685ea8a2394c1265`

The checkout, cooldown overlay, regression gates, pointer verification, package download, and package verification all passed.

## Failure

The production runner stopped at its fail-closed source identity gate:

```text
RuntimeError: main SHA mismatch: expected 887f479b15ad861313da666ad698034d3847121c, got
```

The workflow independently verified the production checkout with `git -C main-src rev-parse HEAD`, but did not export the verified value as `BACKTESTER_MAIN_SHA`. The historical runner intentionally accepts the source identity through that environment contract, so it received an empty value and refused to execute.

## Correction

`backtester/run_production_strict_pit_20y.py` now:

1. resolves the exact `--main-root` used by the invocation;
2. obtains its Git HEAD directly;
3. requires that HEAD to equal the pinned production SHA;
4. rejects a conflicting inherited `BACKTESTER_MAIN_SHA`;
5. binds the independently verified checkout SHA into the runner environment in the same process;
6. exposes `--self-test-source-identity` for an exact preflight.

This preserves fail-closed source identity while removing reliance on an omitted workflow variable.

## Retained evidence

- Workflow run: `33352236633`
- Artifact ID: `9744046103`
- Artifact ZIP SHA-256: `b666e5554b3bfef6d65dc7eb62d5b7f3c9819a1cb1dd368d52211f8f5b3290b1`

The artifact is large because retry 1 included a duplicate copy of the immutable canonical package. Future workflow cleanup should retain the package pointer and verification evidence while excluding the copied package bytes from the run artifact.
