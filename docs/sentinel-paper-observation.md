# PAPER_OBSERVATION_ONLY authority

> **Decision record, 2026-08-15; standing-semantics clarification, 2026-08-21.**
> This mode authorizes an explicitly revocable Alpaca PAPER forward-observation
> trial. It does not certify historical Wealth Core results, does not change the
> `NO-GO`/`HISTORICAL_CAUSALITY_UNVERIFIED` historical record, and cannot
> authorize a live endpoint or account.

## Accepted boundary

Point-in-time historical issuer and sector metadata is unavailable. Historical
CAGR and drawdown therefore remain `HISTORICAL_CAUSALITY_UNVERIFIED`. A
production-style 253-session cold start ending 2026-07-31 produced the same
25-security target and weights with current issuer metadata, identity-only
metadata, and metadata-minimal input. That result is useful forward-observation
evidence and is not historical certification. The signed observation evidence
must retain both facts verbatim.

**Concordance addendum (2026-08-21).** The comparison above establishes the
native Wealth Core target only; it does not authorize backdating the current
TICKERS snapshot through Concordance's zero-capital recent-leadership witness.
On a current-only seed, the 252 prior closes prime price features without
historical decisions, and the witness begins on the first live decision close
with explicit unavailable r20/r40 evidence.  A historically certified start
still requires session-effective metadata for every witness close.  The exact
runtime contract is recorded in
`sentinel-concordance-production-integration.md`.

The existing Wealth Core, controller, execution-membrane, and durability test
surfaces remain the certification path for code that can change strategy
decisions or their implementation. Observation authority neither bypasses nor
renames those verdicts; it binds their exact source/runtime identities and uses
forward paper results as new operational evidence.

`PAPER_OBSERVATION_ONLY` is a second signed certificate schema. It is not a
verdict accepted by `sentinel.paper_execution_certificate/1`, the historical
certificate issuer, or any `GO`/`PASS` certification field. Its claims say:

```text
authorization_mode       PAPER_OBSERVATION_ONLY
historical_causality     HISTORICAL_CAUSALITY_UNVERIFIED
historical_certification NOT_GRANTED
scope                    ALPACA_PAPER
paper endpoint           https://paper-api.alpaca.markets
live promotion           FORBIDDEN
```

The existing Ed25519 trust-root store, canonical encoding, signature checking,
durable install/activation lifecycle, issuer-generation monotonicity,
supersession, key/certificate revocation, rollout transition, and account
binding remain the authority infrastructure. An unsigned candidate or retained
evidence record never confers authority.

## Standing forward-trial authority and explicit stop

The signed observation certificate retains a nominal `not_before`/`expires_at`
window as reviewed evidence and is issued under the existing bounded certificate
schema. That nominal expiry is **not**, by itself, an economic or integrity
failure for an otherwise unchanged `PAPER_OBSERVATION_ONLY` forward trial.
Once activated, ordinary paper-only authority may continue past the nominal
observation window only through the narrow standing-authority loader, which
still requires the same signed certificate, trusted key, active durable
lifecycle, no key/certificate revocation, exact account/deployment binding,
exact rollout, runtime/strategy/configuration identity, publication-chain
lineage, maximum exposure, and current operational gates.

Explicit certificate/key revocation, the durable kill switch, deployment or
account drift, rollout drift, runtime/strategy/configuration drift, publication
or readiness failure, or operator deactivation stops authority independently.
Historical and administrative authority families do **not** inherit this
standing exception. The exception is paper-only and cannot authorize a live
endpoint or turn forward observation into historical certification.

## Signed bindings

Every observation certificate binds all of the following:

- exact Git commit, Sentinel and Wealth Core source identities, requirements
  lock, authorized runtime image digest, and test-image digest;
- current runtime and strategy identity;
- exact execution configuration and automation configuration fingerprint;
- current published corpus version and publication-chain root;
- the complete visible TICKERS snapshot that formed the reviewed activation
  root: date, row count, and canonical content digest;
- exact deployment id, broker, paper account id, takeover epoch, environment,
  and paper URL;
- the next rollout mode/version and predecessor certificate;
- controller rule/configuration identity;
- a Decimal maximum core exposure in `[0, 1]`;
- the canonical retained observation-evidence digest.

The activation-day metadata identity is a **minimum reviewed root**, not a
permanent freeze of TICKERS bytes. The current metadata identity is recomputed
from the newest complete visible `sentinel_universe` snapshot. Missing, empty,
or older-than-root metadata refuses ordinary authority. A newer complete
published snapshot may legitimately differ in row count or content during a
forward trial; the ordinary ingest/publication/readiness path must first make
that newer snapshot authoritative for the relevant decision session. Freezing
activation-day metadata would itself create an artificial kill switch and would
prevent legitimate symbol/listing metadata evolution. Publication policy/root,
runtime image, Git commit, strategy, automation config, deployment/account,
rollout, and maximum exposure remain rechecked before ordinary execution. The
plan is held under the execution writer lock; its target exposure must not exceed
the signed maximum.

The broker-facing adapter still permits exactly
`https://paper-api.alpaca.markets`. The first typed account response must name
the signed and durably bound account, report `ACTIVE`, all three block flags
false, `multiplier == 1`, and cash-only buying power. A configured or signed
identity mismatch is refused before broker construction. A broker-returned
account mismatch necessarily requires the one identity read that discovers it,
but no submission follows it.

## Operational gates are unchanged

Observation authority is additional; it replaces none of these gates:

- current corpus coherence/readiness and current XNYS frontier;
- a 253-session current cold start (252 price-feature warmup sessions plus one
  live decision; Concordance witness history is prospective unless causal
  dated metadata exists);
- verified base backup/WAL status and the independent restore drill;
- disabled-by-default automation and the durable kill switch;
- one fenced leader, writer lock, heartbeat, and takeover generation;
- durable alert outbox and visible dead-letter/unacknowledged counts;
- complete broker reconciliation, terminal recovery, and UNKNOWN handling;
- current, publication-pinned plan and exact plan/state/rollout fingerprints;
- durable deployment/account binding and broker/session/cash checks;
- reductions before increases and the long-only, unlevered execution envelope.

No command in this change contacts Alpaca, migrates an account, starts
automation, changes NAS state, or merges a pull request. Those remain explicit
operator actions below.

## NAS runbook

Run from the exact reviewed commit after its PR is merged. Placeholders are
mandatory operator-reviewed values. `COMPOSE` and the digest-pinned wrapper
retain the meanings in `sentinel-paper-activation.md`.

```bash
COMPOSE="bash scripts/sentinel-compose.sh --run"
export ALPACA_BASE_URL=https://paper-api.alpaca.markets
: "${ALPACA_API_KEY:?paper key required}"
: "${ALPACA_SECRET_KEY:?paper secret required}"
: "${SHARADAR_API_KEY:?Sharadar key required}"
: "${SENTINEL_POSTGRES_PASSWORD:?database password required}"
: "${SENTINEL_BACKUP_DIR:?independent backup target required}"
: "${SENTINEL_GIT_COMMIT:?exact reviewed commit required}"
: "${SENTINEL_RUNTIME_IMAGE_DIGEST:?authorized runtime digest required}"
: "${SENTINEL_TEST_IMAGE_DIGEST:?test image digest required}"
: "${SENTINEL_AUTHORITY_ARTIFACTS_DIR:?authority directory required}"
test "$ALPACA_BASE_URL" = https://paper-api.alpaca.markets
test -d "$SENTINEL_AUTHORITY_ARTIFACTS_DIR"
```

### 1. Backup, data, and current warmup comparison

```bash
bash scripts/sentinel-backup-status.sh
bash scripts/sentinel-restore-drill.sh
$COMPOSE run --rm sentinel feed-daily
$COMPOSE run --rm sentinel check-data --today <POST_CLOSE_ET_ISO_8601>
$COMPOSE run --rm sentinel target-book --sessions 253 \
  --cash <PAPER_ACCOUNT_EQUITY> \
  > "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/current-target-book.json"
bash scripts/sentinel-authorized-cli.sh migration-plan --sessions 253 \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID> \
  > "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/current-migration-plan.json"
$COMPOSE run --rm sentinel compare-paper-warmup \
  --target-book /var/lib/sentinel-authority/current-target-book.json \
  --migration-plan /var/lib/sentinel-authority/current-migration-plan.json
```

The comparison must report 253 measured sessions, 252 warmup sessions, the
same decision session, security membership, and weights. It reports
`HISTORICAL_CAUSALITY_UNVERIFIED`; it never prints `GO`, certified CAGR, or
certified drawdown.

### 2. Bind the exact paper account

#### Preferred path: brand-new, empty, cash-only paper account

Create the bootstrap candidate before a binding exists.  These candidate,
installation, and activation commands are broker-free.  The dedicated offline
issuer uses the already-enrolled Ed25519 key and the existing trusted-root
system; it does not use or print a private key from the runtime.

```bash
$COMPOSE run --rm sentinel create-empty-paper-binding-candidate \
  --certificate-id <UNIQUE_CERTIFICATE_ID> \
  --issuer-generation <MONOTONIC_GENERATION> \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID> \
  --not-before <UTC_SECOND_Z> \
  --reviewer <REVIEWER_ID> --ticket <CHANGE_TICKET> \
  > "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/empty-binding-candidate.json"
python -m tools.sentinel_empty_account_authority issue \
  --candidate "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/empty-binding-candidate.json" \
  --private-key-file <OFFLINE_ED25519_PKCS8_KEY> \
  --key-id <ENABLED_TRUSTED_KEY_ID> \
  --output "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/empty-binding-certificate.json" \
  --confirm-issue-admin-bind-empty
EMPTY_BIND_CERT_SHA256="$(sha256sum "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/empty-binding-certificate.json" | awk '{print $1}')"
bash scripts/sentinel-authorized-cli.sh install-administrative-certificate \
  --certificate /var/lib/sentinel-authority/empty-binding-certificate.json \
  --confirm-certificate-sha256 "$EMPTY_BIND_CERT_SHA256" \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID> --takeover-epoch 1 \
  --reason '<CHANGE_TICKET>' \
  --confirm-install-administrative-certificate
bash scripts/sentinel-authorized-cli.sh activate-administrative-certificate \
  --certificate-sha256 "$EMPTY_BIND_CERT_SHA256" \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID> --takeover-epoch 1 \
  --reason '<CHANGE_TICKET>' \
  --confirm-activate-administrative-certificate
```

Inspect and bind only the exact named account.  Both broker commands use the
read-only `ADMIN_BIND_EMPTY` facade.  The binding command performs its own two
stable complete flat observations; inspection output is not cached authority.

```bash
bash scripts/sentinel-authorized-cli.sh inspect-empty-paper-account \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID>
bash scripts/sentinel-authorized-cli.sh bind-empty-paper-account \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID> \
  --notes '<CHANGE_TICKET>'
$COMPOSE run --rm sentinel status
```

`status` must show one epoch-1 `SENTINEL_OWNED` binding and the bootstrap
certificate as `REVOKED`, with the consumption reason.  The account must be
ACTIVE, unblocked, multiplier 1, cash-only and settled, with zero positions and
zero open orders throughout both reads.  Any other result is a refusal, not a
reason to switch to migration.

#### Inherited account: administrative migration

Use the stronger administrative-certificate procedure in
`sentinel-paper-activation.md` only when the account actually contains an
inherited book, then:

```bash
bash scripts/sentinel-authorized-cli.sh inspect-paper-account \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID>
bash scripts/sentinel-authorized-cli.sh migrate-account \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID> \
  --notes '<CHANGE_TICKET>'
bash scripts/sentinel-authorized-cli.sh inspect-paper-account \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID>
$COMPOSE run --rm sentinel status
```

Migration is optional for an already-owned, correctly bound, fully reconciled
account. It is not the fresh-empty-account enrollment path and its historical
certification requirements are unchanged. Never run it twice. The postcondition is an exact
`SENTINEL_OWNED` binding and two stable flat observations, not merely an
accepted cancel or sell.

### 3. Create, review, sign, install, and activate the standing trial root

Candidate creation is database-read-only and broker-free. The command captures
one UTC lifecycle reference **before** readiness and the 253-session warmup are
computed; `issued_at` and the `not_before >= issued_at` check use that same
reference, so construction time cannot consume the operator's activation
margin. A correctly signed future-dated certificate may be installed as
`STAGED` before `not_before`, but activation and all ordinary authority remain
refused until `not_before` is reached. The certificate schema still requires a
bounded nominal expiry window (use the issuer's default or an accepted explicit
`--expires-at`); standing `PAPER_OBSERVATION_ONLY` operation does not treat that
nominal expiry alone as an automatic stop after activation.

```bash
$COMPOSE run --rm sentinel create-paper-observation-candidate \
  --certificate-id <UNIQUE_CERTIFICATE_ID> \
  --issuer-generation <MONOTONIC_GENERATION> \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID> \
  --not-before <UTC_SECOND_Z> \
  --maximum-exposure <DECIMAL_0_TO_1> \
  --cash <PAPER_ACCOUNT_EQUITY> \
  --reviewer <REVIEWER_ID> --ticket <CHANGE_TICKET> \
  > "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/observation-candidate.json"
python -m tools.sentinel_observation_authority issue \
  --candidate "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/observation-candidate.json" \
  --private-key-file <OFFLINE_ED25519_PKCS8_KEY> \
  --key-id <ENABLED_TRUSTED_KEY_ID> \
  --output "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/observation-certificate.json" \
  --confirm-issue-paper-observation-only
OBS_CERT_SHA256="$(sha256sum "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/observation-certificate.json" | awk '{print $1}')"
bash scripts/sentinel-authorized-cli.sh install-system-certificate \
  --certificate /var/lib/sentinel-authority/observation-certificate.json \
  --confirm-certificate-sha256 "$OBS_CERT_SHA256" \
  --reason '<CHANGE_TICKET>' \
  --confirm-install-alpaca-paper-execution-certificate
bash scripts/sentinel-authorized-cli.sh activate-system-certificate \
  --certificate-sha256 "$OBS_CERT_SHA256" \
  --confirm-paper-account <PAPER_ACCOUNT_ID> \
  --confirm-deployment-id <STABLE_DEPLOYMENT_ID> \
  --reason '<CHANGE_TICKET>' \
  --confirm-controller-rollout \
  --confirm-activate-alpaca-paper-execution-certificate
```

### 4. Prepare, start, and observe automation

```bash
bash scripts/sentinel-authorized-cli.sh prepare-paper-plan \
  --through <DECISION_CLOSE> --warmup-sessions 252 \
  --expect-account <PAPER_ACCOUNT_ID>
$COMPOSE run --rm sentinel current-paper-plan
bash scripts/sentinel-authorized-cli.sh activate-paper-automation \
  --confirm-paper-account <PAPER_ACCOUNT_ID> \
  --confirm-deployment-id <STABLE_DEPLOYMENT_ID> \
  --confirm-certificate-sha256 "$OBS_CERT_SHA256" \
  --actor <OPERATOR> --reason '<CHANGE_TICKET>' \
  --confirm-old-writer-fenced \
  --confirm-enable-unattended-alpaca-paper-automation
bash scripts/sentinel-automation-compose.sh up -d sentinel-automation
bash scripts/sentinel-authorized-cli.sh release-paper-automation-kill-switch \
  --confirm-paper-account <PAPER_ACCOUNT_ID> \
  --confirm-deployment-id <STABLE_DEPLOYMENT_ID> \
  --confirm-certificate-sha256 "$OBS_CERT_SHA256" \
  --actor <OPERATOR> --reason '<CHANGE_TICKET>' \
  --confirm-release-unattended-paper-kill-switch
$COMPOSE run --rm sentinel automation-status
$COMPOSE run --rm sentinel status
```

Status and the SELECT-only panel must visibly show
`PAPER_OBSERVATION_ONLY`, nominal certificate expiry,
`HISTORICAL_CAUSALITY_UNVERIFIED`, maximum exposure, lifecycle/current verdict,
leader fence/expiry, last clean reconciliation, next cycle, and alert counts.
The nominal certificate expiry remains evidence; standing paper authority still
fails on explicit revocation/kill or any of the exact runtime/account/data/config
checks described above.

### 5. Kill, stop, or deliberately rotate

Emergency kill and planned stop do not require a currently time-valid nominal
certificate window:

```bash
bash scripts/sentinel-authorized-cli.sh engage-paper-automation-kill-switch \
  --actor <OPERATOR> --reason '<WHY>'
bash scripts/sentinel-authorized-cli.sh deactivate-paper-automation \
  --actor <OPERATOR> --reason '<WHY>'
bash scripts/sentinel-automation-compose.sh stop sentinel-automation
$COMPOSE run --rm sentinel automation-status
```

Those are also the exact commands for a planned stop whenever the operator
chooses; there is no hardcoded observation end date.

Rotation is **not required merely because the nominal observation window has
passed**. Rotate deliberately when changing the reviewed authority root (for
example configuration, maximum exposure, deployment/runtime lineage, or an
operator-selected credential refresh). Candidate creation reads the active
predecessor from durable rollout state; it does not take a hand-entered
predecessor flag. Rotation recomputes current corpus, metadata,
runtime, strategy/controller, account, configuration, warmup, and exposure
facts. It remains a paper-only authority transition, not historical
certification.

If a rotation is deliberately chosen, create and issue
`observation-certificate-next.json`, then rotate without an unfenced writer:

```bash
CURRENT_OBS_CERT_SHA256="$OBS_CERT_SHA256"
NEXT_OBS_CERT_SHA256="$(sha256sum "$SENTINEL_AUTHORITY_ARTIFACTS_DIR/observation-certificate-next.json" | awk '{print $1}')"
bash scripts/sentinel-authorized-cli.sh engage-paper-automation-kill-switch \
  --actor <OPERATOR> --reason '<AUTHORITY_ROTATION>'
bash scripts/sentinel-authorized-cli.sh deactivate-paper-automation \
  --actor <OPERATOR> --reason '<AUTHORITY_ROTATION>'
bash scripts/sentinel-automation-compose.sh stop sentinel-automation
bash scripts/sentinel-authorized-cli.sh install-system-certificate \
  --certificate /var/lib/sentinel-authority/observation-certificate-next.json \
  --confirm-certificate-sha256 "$NEXT_OBS_CERT_SHA256" \
  --reason '<AUTHORITY_ROTATION>' \
  --confirm-install-alpaca-paper-execution-certificate
bash scripts/sentinel-authorized-cli.sh rotate-system-certificate \
  --certificate-sha256 "$NEXT_OBS_CERT_SHA256" \
  --confirm-supersedes-certificate-sha256 "$CURRENT_OBS_CERT_SHA256" \
  --confirm-paper-account <PAPER_ACCOUNT_ID> \
  --confirm-deployment-id <STABLE_DEPLOYMENT_ID> \
  --reason '<AUTHORITY_ROTATION>' --confirm-controller-rollout \
  --confirm-rotate-alpaca-paper-execution-certificate
OBS_CERT_SHA256="$NEXT_OBS_CERT_SHA256"
bash scripts/sentinel-authorized-cli.sh activate-paper-automation \
  --confirm-paper-account <PAPER_ACCOUNT_ID> \
  --confirm-deployment-id <STABLE_DEPLOYMENT_ID> \
  --confirm-certificate-sha256 "$OBS_CERT_SHA256" \
  --actor <OPERATOR> --reason '<AUTHORITY_ROTATION>' \
  --confirm-old-writer-fenced \
  --confirm-enable-unattended-alpaca-paper-automation
bash scripts/sentinel-automation-compose.sh up -d sentinel-automation
bash scripts/sentinel-authorized-cli.sh release-paper-automation-kill-switch \
  --confirm-paper-account <PAPER_ACCOUNT_ID> \
  --confirm-deployment-id <STABLE_DEPLOYMENT_ID> \
  --confirm-certificate-sha256 "$OBS_CERT_SHA256" \
  --actor <OPERATOR> --reason '<AUTHORITY_ROTATION>' \
  --confirm-release-unattended-paper-kill-switch
$COMPOSE run --rm sentinel automation-status
```
