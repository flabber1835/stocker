# Economic audit #399: lifecycle checkpoint 1

Pinned production SHA: `aff4461d9af6d4a7367018768fda18d948958b49`.
Tree: `56790bb69b1c65b981ffee94c2a58542916b3b52`.
Audit evidence only. Production source and real account state remain unchanged.

## Executed sources

The adjacent four Python files are the exact executed probe sources and fixture.
- F5 abrupt callback death: 2 passed in 2.52 seconds. Ledger comment 5722779698.
- F11 cash mismatch identity and crash controls: 5 passed in 1.88 seconds. Comment 5722799379.
- C3 / strict ownership: 2 passed in 1.88 seconds. Comment 5722863172.

These passes establish baseline counterexamples and fail-closed boundaries. They are not post-fix acceptance.

## Runtime and reproduction

Python 3.12.13 from the retained image artifact; disposable PostgreSQL 17.
Load unchanged pinned source and its locked dependencies. Put this probe folder outside
production tests and run pytest with `--confcutdir` pointing here. Set `PYTHONPATH` to
the pinned repository and its `shared` directory. Set a nonproduction
`SENTINEL_PUBLICATION_RECEIPT_KEY` and the recorded image/source revision identity.
The shared fixture uses the repository's ephemeral PostgreSQL helper. It disables the
physical NAS backup marker for the synthetic command-journal database.
The strict-policy cases import execution in fresh processes with `STRICT_V1` enabled.
The other probes use segmented real production paths with explicit controlled dependencies.
F5 uses an audit-only SQL broker ledger. Cash parser HTTP payloads are fixtures.
The crash cases send actual SIGKILL and inspect durable SQL after process death.
No Alpaca connection or real account mutation occurred.

The recovered chroot lacks a mounted `/proc` and native `/dev/urandom`. Its `/dev/null`
was a world-writable regular file. OCI whiteouts were not applied during extraction.
These qualifications exclude claims of host/NAS equivalence or physical restore acceptance.

## Supporting regression evidence

Automation scheduler/service/store: 56 passed in 11.90 seconds.
Runtime backup authority/integrity, service policy, deployment PITR, restore validation
and upgrade fencing: 145 passed in 5.95 seconds. Counts overlap other campaigns.

The local downloadable evidence ZIP contains original logs, JUnit, runner, source and
SHA-256 manifest: `audit399-lifecycle-checkpoint-1.zip`, 16,170 bytes,
SHA-256 `6d78fd123d4e1edcba45bc2399ab448e714bc46121289cbfb0a9fc3e53fe91d7`.
The ZIP itself is a conversation artifact; the probe sources are retained in this branch.

The canonical ledger is #399. Source-review exhaustion and economic sign-off remain open.
