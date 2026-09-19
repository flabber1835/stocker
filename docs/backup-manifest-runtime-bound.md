# Bounded runtime manifest inspection

Step 1 review against main `65e261312ec219e014f062c0b6b374066db19d75`
found that runtime restore authority used `pg_read_file(path)::jsonb` without a
byte limit. The preliminary completeness probe also decoded an arbitrary first
MiB of the manifest, which can split a UTF-8 character. Neither operation needs
unbounded content to establish the selected base's final WAL range.

Before implementation, the runtime contract is changed as follows:

- Completeness discovery probes one binary byte of the manifest. Presence is
  only a candidate test; it grants no restore authority. Selected manifests
  still require a valid final WAL range and the existing complete archive proof.
- The selected manifest is read once with an explicit **8 MiB + one byte** cap.
  The extra byte distinguishes an exactly-at-limit complete file from a longer
  file whose prefix happens to be valid JSON. PostgreSQL materializes this
  bounded payload before any JSON conversion. Only payloads of at most 8 MiB
  may be decoded and parsed. Oversize refuses before JSON parsing; malformed
  in-budget content also refuses. There is no fallback to an older base after
  the selected manifest is refused, and no retained proof is advanced.
- Eight MiB is a new conservative admission ceiling, not evidence that all
  deployed manifests fit. Operators must measure retained manifests and the
  complete authority call on the accepted image before NAS qualification.
  Larger manifests remain unsupported until a separately reviewed bounded
  reader design is accepted. Do not silently truncate or increase the ceiling
  to obtain green qualification.

The [PostgreSQL 16 file API](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADMIN-GENFILE)
defines explicit binary read lengths in bytes. Binary presence probing avoids
text-decoding boundary errors. A materialized payload and guarded JSON
conversion keep both read and parser input finite even if the file grows before
the SQL read. This is not a filesystem snapshot or authentication of mutable
base metadata; existing immutable producer, verification and alias checks
remain required. No cache, schema, backup format or producer changes are added.

Acceptance must exercise actual PostgreSQL with valid short and exactly-at-limit
manifests, an oversize valid JSON prefix, invalid bytes beyond the budget,
multi-byte content spanning the old probe boundary, missing/malformed files,
and repair. A sparse large file checks refusal without full JSON materialization.
Production `require` must refuse an oversized newest selected base despite an
older valid candidate and then succeed after repair. Falsifiers remove the extra
byte, remove the parse gate, remove oversize refusal, or restore the text probe;
each must fail a behavioral acceptance assertion.

Directory discovery remains open: the
[PostgreSQL directory implementation](https://doxygen.postgresql.org/genfile_8c_source.html)
materializes directory entries internally, so adding a SQL LIMIT would bound
client rows but would not close backend enumeration cost. A bounded publication
index or dedicated reader requires a separate ownership/lifecycle design.
Recurring verified backups, proactive horizon rollover and retention also
remain open. This change does not qualify blocked filesystems or NAS latency.

## NAS handoff

After reviewed merge and exact-head CI, use a disposable clone with no broker
credentials. Record the accepted source/image/database identities and largest
retained manifest byte size; any manifest over 8 MiB fails this admission gate.
Run the retained local regression/mutation commands on that image. Retain raw
logs, refusal/recovery evidence and resource measurements. Require all positive
cases to pass and every mutant to fail at its intended assertion. Measure the
complete production authority call under configured memory and callback
deadlines on populated media. An OOM, timeout, oversized manifest or granted
authority after a fault fails qualification. No NAS action is performed here.
