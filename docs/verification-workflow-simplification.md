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
* Keep the old-image and candidate-image canonical comparisons before stopping
  applications and the independent candidate check after shadow starts. The last
  check observes a newly started process context. Reusing its earlier result was
  considered and is not selected in this change: removing that boundary requires
  a separate startup-integrity argument. Source, broker and intent-only repetition
  can be removed without changing this financial gate.
* Remove the obsolete in-panel monitor implementation from production. The
  independent verifier service and authenticated durable projection remain the
  single current path. Historical regression support belongs under tests/support.
  Preserve historical data-format readers needed by the retained canonical book.

Fresh broker account identity, kill switch, leader/fence, unknown outcomes and
final submission envelopes retain their existing execution checks. These observe
facts that can change during a network call. Signature/source duplication may be
removed only without losing those mutable checks. Backup and recovery contracts
are unchanged by this cleanup.

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
