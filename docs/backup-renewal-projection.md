# Independent backup renewal is an explicit operating phase

Decision: 2026-11-09, before implementation. At 09:04:55Z the independent
maintenance owner committed BASE_BACKUP progress for the currently selected
predecessor. Physical creation completed at 09:13:19Z; chain verification
completed at 09:13:23Z. The last ordinary chain observation, at 08:59:50Z,
expired at 09:09:50Z. The dashboard treated that scheduled renewal as failure,
then retained an acknowledgement latch after successful recovery.

Two projection assumptions conflict with the selected architecture. Progress
belongs to the qualified independent maintenance producer, whose immutable
image need not equal the application image. BASE_BACKUP is a real, bounded
phase, already committed by that producer and enforced by the database's
append-only attempt/phase guard. It must be understood by the same projection
that already understands VERIFY_CHAIN and VERIFY_RESTORE.

Remove the application-image comparison from this nonfinancial progress
projection. Continue validating the immutable producer-image syntax, physical
database identity, exact predecessor/successor lineage, producer observation,
original attempt start and immutable deadline. The database evidence writer and
attempt-transition guard remain the provenance boundary, as for the other
backup evidence consumed here. Neither progress text nor an application image
string proves byte integrity or authorizes a broker operation.

During BASE_BACKUP, accept only the still-selected predecessor: progress base,
progress predecessor, verified base and last verified runtime chain must all
name that same generation. The chain must have been current when the attempt
started. A bounded, authenticated copy in progress may explain only the normal
chain-cadence gap; it cannot excuse a cluster/base mismatch, malformed or failed
integrity evidence, an old base, an expired drill, a future observation, failed
or completed progress, or an expired attempt. Preserve the existing one-hour
maximum attempt budget and original deadlines without renewal.

Keep successor verification restricted to its existing exact transition and
VERIFY_CHAIN/VERIFY_RESTORE phases. COMPLETE must return to an independently
current successful chain. FAILED remains a failure. This is presentation of
ordinary maintenance, with explicit BACKUP_MAINTENANCE recovery evidence; it
does not extend the ten-minute ordinary chain clock, runtime byte-proof cache,
financial backup admission, retention authority or maintenance policy.
The headline treats only this exact validated maintenance row as ordinary
scheduled work. It must not create FAILED/REVIEW history merely for healthy
renewal, then demand acknowledgement after success. Any independent failure,
invalid progress or exhausted original attempt remains visible and reviewable.

Replay the actual observed phases and clocks with a maintenance image distinct
from the application. Exercise deadline expiry, dead/missing/foreign/failed
progress, lineage mismatch, hard proof failures and completion without a new
chain. Require an executed falsifier for the new phase/lineage guard. Deploy
only the application projection change; preserve the qualified independent
maintenance process and its configuration.
