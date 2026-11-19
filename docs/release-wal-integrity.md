# WAL verification during backed PAPER release

In the PR 607 installation trace, maintenance read 241 archived segments twice.
About 61 seconds later the activation checkpoint traversed those segments and
its new segment using the standalone status checker. The two checkers did not
share byte evidence. The following maintenance renewal performed its scheduled
full scrub. The trace did not record the range of the earlier GO status check.

Backed PAPER GO and activation consume the common physical integrity proof.
Release consumers request ordinary admission. Maintenance alone requests early
full renewal. The release must verify the currently published base, its marker,
archive implementation and frontier on the current primary. It may consume
only an authenticated receipt for the same checker, base, start, geometry and
physical primary/boot. The ordinary checker reobserves files and sidecars and
hashes newly appended segments twice. Prefix changes, a missing receipt or an
expired original byte proof require full verification. A metadata observation
or successful suffix check cannot extend the original 300-second window.
Scheduled full rehashing remains necessary to detect same-metadata corruption.

While another process owns the byte checker, a release may consume an exact
completed proof only if its bytes, physical identity and original clock remain
valid through admission. An uncovered frontier joins the existing owner within
the release status deadline. No competing standalone scan is launched.
Backup creation, retention and the activation WAL barrier still obey the
target lock. The activation checkpoint rechecks the selected generation and
proves the committed boundary through the newly archived WAL before publishing.
Full and physical restore drills retain their separate qualification.
