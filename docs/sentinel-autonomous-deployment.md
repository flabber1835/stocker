# Autonomous Sentinel ALPACA PAPER deployment

This is the supported one-command deployment path for the risk-contained Alpaca
paper environment:

```bash
cd /path/to/stocker
bash scripts/sentinel-autonomous-deploy.sh
```

Running `git pull --ff-only` first is harmless but not required. The launcher
requires a clean `main`, performs its own fast-forward-only pull, and re-execs
the freshly pulled launcher if HEAD changed. It never uses `git reset`, never
discards local work, and never changes branches by guessing.

## One-time configuration

Copy `.env.example` to `.env` and keep the normal Sentinel database, Sharadar,
Alpaca PAPER, and backup values populated. Autonomous deployment additionally
requires:

- `SENTINEL_DEPLOYMENT_ID` — the exact durable Sentinel deployment id.
- `SENTINEL_PAPER_ACCOUNT_ID` — the exact Alpaca paper account number/id.
- `SENTINEL_RUNTIME_IMAGE_REPOSITORY` and
  `SENTINEL_TEST_IMAGE_REPOSITORY` — registry repositories without a tag or
  digest. Docker registry authentication must already work on the NAS.
- `SENTINEL_AUTHORITY_ARTIFACTS_DIR` — retained local/durable deployment and
  signing evidence.
- `SENTINEL_DEPLOY_SIGNING_KEY_FILE` — Ed25519 private key outside the Git
  checkout, normally on the separately controlled USB/key location.
- `SENTINEL_DEPLOY_SIGNING_KEY_ID` — the corresponding committed ACTIVE trust
  root id.

The deployer does **not** enroll or rewrite trust roots. Changing the configured
private key is therefore a safe way to select a different already-enrolled
signer, but an unknown/disabled/revoked signer refuses before the deployment
transition begins.

For an already owned NAS account, leave
`SENTINEL_DEPLOY_ALLOW_EMPTY_BIND=0`. A truly new, known-empty paper account can
set it to `1` for first enrollment. That path still uses a dedicated signed
`ADMIN_BIND_EMPTY` certificate and refuses any observed position or working
order. There is deliberately no automatic inherited-book migration.

## What the deployer does

Before disturbing the running system it verifies Git, performs a read-only
Alpaca paper-account identity/cash check, builds the exact Sentinel ordinary,
authorized, and test images, runs the complete Sentinel test suite with skips
refused, freezes the image build identity, pushes runtime/test images, and
resolves immutable registry RepoDigests. A registry/build/test/signing-key
failure at this stage leaves the existing deployment untouched.

Only then does it enter the fail-closed transition boundary. From that point any
exception or Ctrl-C attempts the minimal emergency kill and directly stops any
running Sentinel automation container. The deployer then:

1. fences/stops old automation;
2. starts only the preserved behavioral PostgreSQL volume;
3. takes a fresh physical base backup and proves a restore drill **before**
   explicit schema migration;
4. runs schema migration while automation is stopped and requires the durable
   kill fence afterward;
5. deactivates the prior automation generation if one exists;
6. runs `feed-daily` and the complete data-readiness contract;
7. verifies the canonical PostgreSQL account binding (or performs the opt-in
   strict-empty first enrollment);
8. derives the next issuer generation and exact predecessor from PostgreSQL;
9. creates the current 253-session `PAPER_OBSERVATION_ONLY` candidate;
10. signs inside the exact new test image with `--network none` and the private
    key mounted read-only;
11. installs the new certificate as STAGED, waits for `not_before` only when
    needed, and activates/rotates the exact predecessor;
12. prepares and re-reads the current durable paper plan;
13. activates automation while its kill switch is still engaged;
14. starts the digest-pinned unattended service;
15. releases the kill switch;
16. requires `LEADER_ACTIVE`, current PASS authority, no latched failure or
    dead-letter alert, then waits through another heartbeat and proves the same
    generation/holder/fence has advanced its heartbeat;
17. persists only non-secret Git/image digest facts back to `.env`;
18. takes a post-deployment base backup and retains a JSON deployment receipt.

On PASS the terminal ends with:

```text
DEPLOYMENT PASS: autonomous Alpaca PAPER trading is authorized and operational
```

Anything else is a failed deployment. Do not infer success from container
presence alone.

## Synology and today's failure modes

The deployer deliberately reuses the canonical Sentinel Compose resolver rather
than spelling a graph itself. If the host probe selects the Synology-compatible
CPU-free base graph, it generates an automation overlay with only `cpus:` lines
removed; memory and shared-memory limits remain intact. This avoids the
`NanoCPUs can not be set` daemon failure while preserving the resource controls
the host can enforce.

Emergency fencing uses `scripts/sentinel-emergency-kill.sh`, so backup-root
attestation, authorized-runtime variables, broker credentials, and shell-export
of the PostgreSQL password cannot become prerequisites for the risk-reducing
kill operation. Ordinary deployment steps still require and verify the backup
contract.

Runtime startup does not perform hot authority-table DDL. Schema migration is an
explicit deploy phase while automation is stopped, and its lock wait is bounded.
The paper-observation lifecycle clock is captured before its expensive warmup,
so the candidate cannot consume its own `not_before` margin; installation may
stage a future-dated certificate and activation waits for the boundary.

## Recovery after a refusal

The deployer is intended to be rerun after the cause is corrected. It does not
roll the database backward, restore an old certificate, reset the book, or
reseed data because those operations would guess about authority-bearing state.
A mid-deployment failure leaves automation killed/stopped. Correct the reported
external problem (registry, backup medium, feed, broker availability, signing
key, etc.) and run the same command again.

The attempt directory under
`$SENTINEL_AUTHORITY_ARTIFACTS_DIR/deployments/` retains command logs, image
build/promotion records, signed candidates/certificates, and—on success—the
final deployment receipt.
