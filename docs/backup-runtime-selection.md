# Bounded runtime base selection

Decision recorded before implementation on main
`58c3e071ede06c176e1ed814fb1a7e35b13c33b2`.

Foreground runtime must not enumerate the retained base directory. PostgreSQL
materializes `pg_ls_dir`; SQL LIMIT does not bound that operation. Replace
discovery with `/sentinel-backup/base/.sentinel-runtime-base-<system_identifier>-v1`.
The ASCII selection record contains exactly three lines and a final newline:

```text
schema=sentinel.runtime-base/1
system_identifier=<current PostgreSQL system identifier>
base_backup=base-YYYYMMDDTHHMMSSZ
```

This is a selection hint, never restore authority. Read at most 257 bytes and
refuse more than 256, require exact schema/cluster/name/format, then retain all
existing completeness, manifest, recovery-marker, WAL, hash and alias checks.
Missing selection is retryable unavailability; malformed/oversized selection
is an integrity refusal. There is no directory fallback, including on restart.
Reject symlink/hardlink selection along with existing metadata aliases. Reread
the selection after the full proof; a change makes the observation retryable.

Explicitly requested bases in the existing physical/GO checkpoint protocol
remain independently validated without requiring this hint. Ordinary runtime
callers omit that argument and must consume the published hint.

## Producer and failure boundaries

The root-owned base-backup command publishes selection only after
`pg_verifybackup`, post-base WAL marker confirmation, metadata grants, atomic
base promotion and directory sync. A small helper validates cluster/final name,
writes a private temporary file in the base directory, grants root:postgres
0640, syncs it, atomically renames it over the cluster selection and syncs the
parent. Publication failure cannot report successful backup completion. No
application table/schema is required; pre-migration GO remains supported.

Before rename, failure leaves the previous record intact (or absent). After
rename, readers see the complete new record. A later operator-evidence insertion
failure does not invalidate verified physical media. An orphan promoted base
is not automatically adopted: retry the reviewed backup command. Old bases
remain retained. Future retention must preserve the selected base until its
successor has been durably selected.

Existing host-lock scope is unchanged. Cross-host/cross-UID serialization and
monotonic newest-base selection are not established: a selected older base
must still prove the current complete restore chain and may hit resource bounds.
Single-owner scheduling/retention remain separate open maintenance gates.

The unprivileged internal-state laboratory models this producer after actual
`pg_verifybackup` and archived recovery-marker confirmation. It atomically
publishes the same selection format in its owned temporary cluster directory,
with file and directory sync. This fixture does not establish production
root:postgres ownership; the actual shell-publisher tests own that acceptance.
Its missing-selection negative control must still refuse ordinary admission.
The simulated composition producer must likewise select its new generation;
leaving the old selection must retain the old recovery horizon and refuse when
that horizon exceeds the existing integrity budget.

## Rollout and qualification

Installations without a record refuse default runtime admission until the
updated backup command creates a fresh verified base. Never hand-write a record,
fall back to discovery, enable a capability or repin a fixture for acceptance.
The record must survive host restart and remain readable by PostgreSQL without
granting access to private base payloads.

Local acceptance covers actual shell publication and PostgreSQL bounded reads,
restart, missing/corrupt/wrong-cluster records, aliases, interrupted publication
and many unrelated generations. A query tripwire must reject directory scans.
Exercise the full writer gate as well as the reader helper; remove new guards
to prove their tests fail.

NAS qualification still requires accepted image/kernel/filesystem, actual
power-loss/rename/directory-sync behavior, permissions and external health.
Local tests do not prove filesystem progress. Host status/restore inspection
and producer cleanup can still enumerate media; their bounds and recurring
backup/horizon maintenance remain open. No NAS or account access is authorized.
