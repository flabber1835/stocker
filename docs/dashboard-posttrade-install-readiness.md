# Post-trade installation and operator review

Decision 2026-11-09, before implementation. The numeric dashboard correction is
running, but the backed installer stopped at APPLICATIONS_STARTED: the strict
post-trade panel validator required automation_alerts=OK while one delivered,
resolved WAITING_FOR_LEADER incident still awaited operator acknowledgement.
All services were healthy, current financial/trading facts were intact, and
the dashboard had no active/review warning conditions. The original finite
readiness interval subsequently expired. Preserve both refusal and old deadline.

Installation verification and owner acknowledgement are separate authorities.
The installer must not acknowledge incidents or require acknowledgement of
settled notification history to finish a software-only repair. Extend the
already-selected reviewed-amber installation allowance to completed POST_TRADE:
require a current strict observation, the unchanged completed plan/cycle,
healthy required capabilities and sender, no current negatives/source errors,
and a current validated review with no active conditions or warnings. A
non-required, fresh historical notification WARN may remain under REVIEW;
record the restricted installation scope and operational_ready=false rather
than claiming an acknowledged green interval. Preserve all notification rows.
An active sender failure or financial/required negative still refuses.

Human display CURRENT is no longer sufficient for installer readiness. Consume
the explicit strict_current dimension (legacy current only when the explicit
dimension is absent). A proved human-only view may wait inside the original
finite readiness interval but cannot satisfy the strict validator. Preserve
negative precedence and bounds while waiting. Do not reinstate broad grey UI
currentness or require a future plan after today's completed trading cycle.
Validate the public JSON currentness/status/payload contract directly. Do not
import a private UI row predicate and call it with incomplete stand-in models;
that duplicates dependency ownership and breaks as the runtime model evolves.

Extend the existing explicit backed final-verification recovery command from
PRE_OPEN to already-started, completed POST_TRADE. It is a new named, journaled
600-second observation, never a replay or renewal of the expired installation.
Require original application process identities, unchanged installed candidate
configuration/source, REQUIRED_V1 backing, unchanged physical/economic state,
fresh canonical proof, advancing current leader and a fresh strict published
panel. Retain the original receipt hash and refusal; record authority_effect=NONE.
Do not rebuild, restart services, edit receipts, reset the old readiness clock,
alter financial authority or replay orders. Other handoff modes remain refused.

Return a finite panel-validity boundary for post-trade recovery as well as
pre-open recovery, and check it after final preservation checks. Qualification
must falsify wrong/unsettled modes, changed process/configuration/economics,
active negatives, expired publication, human-current/strict-false pages, and
unreviewed notification failures. Use the qualified host tooling to finish the
already-installed operation; no application image change is needed for these
host-only readiness corrections.
