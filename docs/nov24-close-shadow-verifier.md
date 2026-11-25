# November 24 close SHADOW verifier admission

The November 24 PAPER close published rolling source version 29 at 21:13:53 UTC.
The signed SHADOW rolling authority for that session was observed at 21:16:22
UTC. A full SHADOW verification performed between those events can become
superseded when the rolling cursor commits, requiring another full read. The
first scan's admission timestamp was not retained, so this is a bounded
scheduling remedy for a plausible cause, not a claim that the first scan was
proven redundant. The retained checkpoint shows a 21:16:22 UTC candidate
observation, but the worker attempt start was not retained; therefore the
after-publication worker gate may have declined this particular close. It does
not change the source, controller or execution.

The worker must already be active when the verifier sees the changed subject.
If the verifier polls first, normal work starts and is never paused later.
This is another reason the November 24 savings cannot be claimed in advance.

## Decision

The verifier may briefly defer **admission** of a changed-subject SHADOW full
read when an authenticated SHADOW worker launched after the new publication is
active. Its signed pending record does not identify the publication or session;
this is only a bounded scheduling hint. The decision uses a cheap, read-only
projection, never the full `prepare_shadow_wait.observe` closure or a bar scan.
It requires all of:

* a signed, validated rolling publication that is the direct successor of the
  publication bound to the last signed ordinary SHADOW authority;
* the exact prior HMAC-valid SHADOW verification receipt, still valid for its
  original subject and showing all SHADOW financial rows positive or the
  documented dated source-frontier wait shape; no failed, unrelated warning
  or expired result qualifies;
* an exact publication-only subject change: reconstruct the prior SHADOW
  subject from one coherent current inventory by removing only the new
  publication row, and require it to match that prior signed receipt. Any
  cursor, environment, installation or DDL change instead starts the scan;
* the signed bound PUBLISHED close job with its original deadline;
* a fresh signed RUNNING/ACTIVE_WORKER SHADOW supervisor status and matching
  signed pending attempt that started after the new publication; and
* an idle verifier observer slot. If another financial check is running or
  queued, the SHADOW check joins the ordinary queue immediately. Its queue
  budget cannot be funded by this wait.

The wait expires at the earliest of publication time plus **180 seconds**, the
original close-job deadline, the original worker deadline, the prior receipt's
original expiry minus the full 300-second verification work allowance and one
15-second owner poll, the next session open, or the reader's original
supersession deadline minus its 300-second work allowance and one owner poll.
Neither a new worker heartbeat nor an owner restart moves the
publication-anchored cap. The reader compares the exact new subject computed
from its own identity read with the hint's subject. A mismatch, missing or
invalid evidence, absent/failed/expired worker, completed new authority, or
any reached deadline immediately resumes normal verifier admission. A worker
does not supply financial proof.

During the wait there is no current-subject positive verification receipt.
The dashboard may show the existing bounded amber `CHECK IN PROGRESS` handoff
from the old receipt; it must not show old green financial values as current.
The prior receipt retains its original expiry. Once the SHADOW cursor commits,
the next check verifies the new subject normally. If the worker cannot finish
within the bounded interval, the verifier starts the ordinary full read. PAPER
financial verification and every execution guard remain unchanged.

## Qualification

Private PostgreSQL tests must cover the exact signed direct-successor, job,
worker and receipt chain; publication-only subject equality and unrelated
cursor/environment/DDL changes; the fixed publication cap; each
original deadline; and immediate scan fallback when any prerequisite is
missing, stale, failed or mismatched. A guard-removal falsifier must fail. A
runtime trace after installation is needed to establish whether this avoids
the repeated November 24 pattern in practice; the retained November 24 data
does not establish the first admission time.
