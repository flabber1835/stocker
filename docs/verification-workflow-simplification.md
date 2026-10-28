# Remove repeated work from verification and installation

The October 26 audit measured repeated responsibilities, not additional financial
facts. The following changes precede the next local installation.

* Validate the shared storage catalog once when constructing a bounded action
  history operation's query router. Reuse that routing decision for the operation's
  price lookups; retain every original price predicate. No connection-global or
  cross-transaction cache is introduced. Standalone readers still validate their
  own structural contract. SQL relation locks and the caller-owned transaction
  retain the read objects for this operation; the operation performs no DDL.
* Let qualification report validation own source-byte hashing. Remove the second
  immediate hash of every identical source file in `Host.verify_candidate`.
* Validate candidate artifacts at the eight actual installation boundaries:
  initial preflight, requesting drain, stopping applications, schema installation,
  Compose installation, runtime identity/shadow start, remaining application start,
  and final verification. Read-only journal-intent transitions do not launch
  another image probe and full source hash. Completed receipt inspection performs
  no runtime qualification. Every resumed mutation still validates its source.
* Compare mutable financial preservation before/after real installation work.
  Remove repetitions on intervening intent-only journal transitions. Read native
  holdings initially, before drain/stop, before starting shadow and other roles,
  and at final verification. Schema pages and file copies cannot contact the
  broker; they retain database/history preservation checks without broker GETs.
* Compare predecessor and candidate canonical facts before stopping applications,
  using the exact retained predecessor fact under the conditions below. At startup,
  require the exact immutable image, healthy process and unchanged full financial
  snapshot instead of scanning the same book again. Keep final current independent
  dashboard verification and the saved-plan/account/leader checks.
* Remove the obsolete in-panel monitor implementation from production. The
  independent verifier service and authenticated durable projection remain the
  single current path. Historical regression support belongs under tests/support.
  Preserve historical data-format readers needed by the retained canonical book.

Fresh broker account identity, kill switch, leader/fence, unknown outcomes and
final submission envelopes retain their existing execution checks. These observe
facts that can change during a network call. Signature/source duplication may be
removed only without losing those mutable checks. Backup archive durability
remains independent of application installation.

Qualification must assert the new exact boundary/call counts and show that a
changed source, book, native holding, control, drain or notification history still
refuses before the corresponding mutation. Include removed-guard falsifiers.
Do not delete a comparison merely because its name contains legacy or because it
has not failed recently.

The structural compatibility record must name the exact final reviewed runtime
bytes for the five changed feed/panel modules. Refresh only those candidate hashes
and the checker's self-normalized profile pin. Preserve the original baseline,
baseline closure, normalized checker implementation, historical policy resources
and `authority_effect=NONE`. This update permits only the reviewed successor;
the complete-file-set and every single-file unknown-byte falsifier remain release
requirements. It is not a new financial authority or a golden-result update.

## Physical traversal versus economic compiler identity

The final qualification exposed that `economic_manifest.identity` hashes whole
`feed.rolling_store` and `feed.action_history` modules as economic input compilers.
The changed functions only traverse stored rows and select an already validated
SQL route. Their logical field/domain/order contract is unchanged and the
independent real-input digest check passed. Treating these reviewed physical
changes as a new strategy would abandon the existing canonical book.

Add one closed physical-read source witness for exactly these two compiler
modules, rooted in C84's actual module hashes. Map only their complete reviewed
successor bytes to the original compiler contribution. Bind the unchanged pure
read contract, the witness implementation, exact member set and full runtime
transition. Preserve the economic manifest's original compiler/dependency maps
and admitted semantic hash; update only its checker implementation pin. Unknown
compiler bytes retain their actual new economic identity, and malformed or
changed witnesses refuse. Other modules cannot gain this mapping. Keep the
existing expected strategy hash and its domain-change falsifier unchanged.

## Separate application installation from physical recovery work

The owner cancelled the October 27 image-specific full restore after it repeated
a database copy and backup verification for a reader-only patch. The local
backed application installer must not require a new RESTORE_DRILL for each image.
It already preserves the exact PostgreSQL image, container, volume and archive-on
configuration, refuses dependency/composition changes, and compares the existing
canonical book with both application images. Keep those real compatibility and
financial boundaries; remove the extra image-specific physical recovery gate.
This decision applies to the local PAPER application adapter, not live activation.

Normal backup maintenance must never invoke a restore drill or renew a base just
because the application image changed. Full recovery drills remain explicit
operator operations. Their original date and image remain visible; do not relabel
an old drill as a test of new code. The dashboard's existing 31-day drill objective
continues to show when a real drill is due.

A newly produced daily base already passes pg_verifybackup and WAL coverage
before promotion. Record its exact four-file metadata digest in BASE_BACKUP
evidence. Retention may consume a separate verified-base-and-WAL-chain receipt,
matching authenticated producer evidence and the freshly verified selected WAL
chain. It is not a RESTORE_DRILL and must never be presented as one. Existing bases
without the new producer digest may use their genuine, exact-base full restore
receipt, irrespective of application image. Wrong system, metadata, marker, WAL
or unverified producer evidence refuses deletion. This keeps daily retention
bounded without another full database copy.

Run the normal maintenance loop every five minutes, rather than every minute.
Within each pass, obtain one full WAL-chain status and use that same observation
for publication and retention. Avoid repeated status scans before and after a
restore that normal maintenance no longer runs. Keep foreground archive-loss,
fresh broker, UNKNOWN order and leader checks unchanged. Qualification is targeted
to these changed operational paths; the already passed reader tests are not
repeated when their source bytes are unchanged.

The first no-copy installation exposed an old-reader circular dependency: its
fresh predecessor scan timed out in the exact sort being repaired. A backed
application roll may reuse its predecessor's retained canonical proof only when
the SHA-bound predecessor receipt/journal, exact old commit/image, full preserved
financial snapshot and retained successor-proof digest all agree. An unchanged
book has no new old-image financial fact to derive. If the current snapshot no
longer matches, use the ordinary fresh predecessor scan. Unknown receipts/proofs
refuse.

The owner then identified the second candidate scan after startup as another
duplicate. The immutable application image and configuration were already bound
to the fresh candidate preflight; startup checks that same image and the complete
preserved financial snapshot before other roles start. A changed book, source
publication, control, history or image still refuses. The old full rescan cannot
prevent a later mutation any more than the retained proof can; both rely on the
same checks before/after subsequent operations. Final completion additionally
requires the independent verifier's current green page with the exact saved plan.
Record startup's method as EXACT_IMAGE_AND_UNCHANGED_SNAPSHOT and retain the
original preflight proof digest; do not describe this as a new full-book scan.
This is installer-only code: qualify and deliver it for subsequent installations
without restarting unchanged application services just to install their installer.
