# Sentinel host environment contract

The host environment is validated before installation performs Git updates,
image builds, receipt-key provisioning, volume permission changes or service
operations. This gate proves configuration completeness and syntax; the existing
database, backup, source-readiness and account-authority gates still prove the
external facts. A fresh installation may have no receipt key: only the existing
locked receipt bootstrap may provision it.

## One parser

`scripts/sentinel_env.py` owns parsing for GO, runtime selection, autonomous
deployment, receipt bootstrap and legacy env conversion. Files are bounded
(1 MiB total, 64 KiB per physical line), regular, readable, non-symlink UTF-8.
One leading UTF-8 BOM is accepted. LF, CRLF, mixed LF/CRLF and a final line with
no newline are accepted. Bare CR, invalid UTF-8, NUL, control/format characters,
Unicode line separators, malformed keys, incomplete assignments, unclosed quotes,
trailing quoted garbage and every duplicate assignment are errors. File identity,
size and timestamps must remain stable across a bounded read.

Keys use ASCII shell identifier syntax. Leading/trailing ASCII spaces and tabs,
blank lines, full-line comments and `export` prefixes are supported. An unquoted
hash starts a comment only after whitespace. Quoted hashes and hashes embedded
in unquoted values are preserved. Quotes are single-line; single quotes support
an escaped single quote; double quotes support escaped quote/backslash. Escaped
control characters in double quotes are refused. Dollar references, backticks
and command substitutions are literal data and are never expanded or executed.
Quote a value containing a whitespace-prefixed hash.
An assignment containing only whitespace and an unquoted comment has an empty
value, including `KEY= # enter the value here` and its tab/CRLF variants.

The entire file is validated even when process variables override its values.
Process environment takes precedence, including an explicit empty override;
required empty values then fail validation. Missing optional env files remain
supported by read-only Python loaders and the ordinary Compose wrapper, with
configuration supplied by the process. Installation requires its persistent
`.env`. Host interpreter/shell injection variables in an env file are refused.

Merging file data into a command environment accepts only `SENTINEL_`,
`SHARADAR_`, `ALPACA_`, and `NDL_` configuration names, plus `GITHUB_TOKEN`,
`GH_TOKEN`, `COMPOSE_DISABLE_ENV_FILE`, and `COMPOSE_ENV_FILES`. Host interpreter
selectors and internal lock/run capabilities are process-only. Other file keys
refuse before any records are exported, even when the process overrides them.
The standalone parser still accepts general identifiers for legacy conversion.
This boundary protects launcher variables, runtime-pointer selection, and host
command execution from file assignments.
GO forwards its command arguments through a separate parser boundary. Only the
requested target affects env preflight; those arguments cannot select a weaker
profile or another env file.

## Stage-specific preflight

The installation/GO/bring-up gates require usable PostgreSQL credentials,
SHARADAR_API_KEY and an absolute backup path. Paper/dual targets additionally
require both Alpaca credentials and the exact paper URL. SHADOW remains broker
free. Blank, whitespace-only and documented placeholder values fail immediately.
PostgreSQL passwords must survive the currently unescaped Compose DSN. Optional
receipt authority is validated when supplied; fresh blank authority is preserved
for the existing ancestry-locked bootstrap. CPU force flags and backup attestation
use the shell's exact 0/1 spelling. Installation retry/timeout and exposure knobs
are checked before side effects using the existing deployment bounds.

Automation interval checks use the effective service defaults from
`docker-compose.sentinel-automation.yml`: lease 12 seconds, heartbeat and control
poll 3 seconds, retry base 5 seconds, retry maximum and callback deadline 900
seconds, and alert maximum attempts 1,000,000. Every validation compares heartbeat
against lease, retry base against maximum, and callback deadline against
heartbeat, including when an operator supplies just one member of a pair.
Regression tests independently resolve the Compose environment and call the real
runtime configuration validator to bind these host defaults to the deployed
service. The standalone runtime model retains its existing defaults.
The alert dispatcher uses that model's 10-second heartbeat because its Compose
environment does not forward the automation lease/heartbeat settings. Installation
and GO for paper/dual targets, plus broker bring-up, also validate its callback
deadline against that effective heartbeat. SHADOW retains its broker-free
preflight and does not require an alert dispatcher.

Broker installation, GO and bring-up require a usable HTTPS
`SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL` before Git, receipt provisioning or
service operations. Missing, empty, comment-only, whitespace-only and placeholder
values refuse, including an explicit empty process override of a configured file.
The setting is listed in `.env.example` and stays operator-owned.

The direct automation Compose wrapper applies the external-alert endpoint and
dispatcher timing prerequisites to potentially mutating or unknown commands before
Docker. The subsequent execution envelope permits the reviewed `up`, `create`,
and `run` surfaces and refuses stale-container transitions (`start`, `restart`,
`unpause`, `pause`) plus generic `exec`. Explicit inspection commands and
`stop`, `down`, `rm`, and `wait` retain maintenance-only prerequisites. The host
classifier consumes the documented [Compose global options](https://docs.docker.com/reference/cli/docker/compose/)
before identifying the command; an unknown command or option selects the
dispatcher requirement. The forwarded argument list has a separate parser
boundary, so an option value named `config` cannot select inspection for `up`.
This helper requires existing receipt authority and supports process-only
configuration.

Webhook URL parsing and property-validation errors become a safe reason code
and key name. Malformed Unicode delimiters, IPv6 authorities and ports never
expose parser exception text. The webhook is also part of GO's shared secret
inventory for streaming diagnostics and validation-bundle scans.

The shared automation Compose graph passes an optional webhook value to the
dispatcher. SHADOW and maintenance also load this graph, and their configuration
must resolve when external alert delivery is unconfigured. The dispatcher retains
its mandatory startup validation. Host regressions compare required service inputs
and the real dispatcher startup contract in addition to automation timing fields.

Durably recoverable account/deployment/image identities and discovered signing
keys retain their existing later discovery gate. Configuration validation does
not claim that market data is ready or that a backup mount is durable.

The ordinary Compose wrapper loads the same validated values before its host
guards, preserving process precedence and the validated-runtime-pointer override.
It uses a NUL-delimited, completion-framed private pipe and Bash `export` with
literal arguments; it never sources operator text or evaluates generated code.
The pipe publishes records only after complete validation. Normal diagnostics
contain reason codes, line numbers and safe key names, never values or raw lines.
Compose's implicit env-file reload is disabled after ingestion so interpolation
and a second file read cannot change the selected values. Alternate Compose env
files must be resolved explicitly before invoking these supported entry points.
The emergency kill script retains its minimal independent configuration path.

Standalone base-backup, backup-status, restore-drill, automation-compose, and
authorized-CLI entry points ingest the same file before their host guards. Their
maintenance profile requires the absolute backup path, PostgreSQL password, and
existing publication-receipt key used by the Compose graph. It accepts a missing
file when those values are supplied by the process. Broker and market-data
credentials retain their operation-specific gates. These helpers never provision
receipt authority. Existing immutable-image and authority-directory guards run
after ingestion. Automation commands additionally apply the operation-aware
dispatcher requirement above.

## Adversarial harness

The ordinary CLI Compose service forwards the existing Sharadar Tables endpoint,
insecure-development opt-in, retry count and backoff settings to the container.
Defaults retain the public HTTPS endpoint and production retry policy. An
explicit insecure-development endpoint permits HTTP export downloads only from
that same configured HTTP origin; other export origins still require HTTPS.
The legacy environment converter deliberately leaves this development opt-in
unset; each development deployment must select it explicitly.

The production GO E2E fixture implements cursor-paginated Tables responses and
complete zipped CSV exports for TICKERS, ACTIONS and SEP. Its 4,000 securities
have complete listing intervals and preserve the production seed population
floor. Before seeding, it inspects the resolved
Compose service and refuses unless the effective endpoint, development opt-in
and retry settings match its local server. It retains the observed request
catalogue and uses only fixture credentials. The real feed acquisition,
normalization, schema, publication and readiness programs consume those
responses. Exact-head and synthetic-merge runs retain their tested SHA while a
temporary local Git remote supplies the required main topology.

`tests/host_python38/test_env_ingestion.py` runs offline with only the standard
library on the minimum supported NAS host and current Python. It exercises the
real parsers, preflight and shell entry points in disposable directories with
recording substitutes for external commands. It checks exact successful values,
failure reasons, zero downstream side effects, secret non-disclosure, file-read
faults, invalid/valid transitions and deterministic corruption campaigns.
Regression falsifiers remove selected guards and require the matching cases to
fail. Existing env publication and receipt-ancestry tests remain required.

Receipt-key and managed-fact writers recognize the same BOM and tab-separated
`export` syntax as the reader, so an accepted first line is updated exactly once.
The legacy converter escapes a final backslash using double quotes to preserve
it through the shared parser. Syntactically valid corruption of a credential
still requires the existing external authentication/readiness checks; this
format has no independent checksum or credential-authenticity proof.
