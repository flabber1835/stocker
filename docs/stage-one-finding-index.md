# Stage 1 finding ownership index

This index assigns every #399 F1–F19/C1–C3 finding and every #400 A1–A27
label to the existing ten-item [closeout checklist](stage-one-closeout-checklist.md).
It adds no work package. It corrects three accounting omissions/misassignments:
F4 preparation jobs and A7 idle retention belong to L08; A8 belongs to L04;
A9/A10 belong to L05. A21's restore extension belongs to L06.

#400 reused **A4, A5 and A6**, not only A5/A6. Distinct rows below retain the
original comment identity. An extension is attached to its original requirement,
not counted as a fresh generic review gate.

The owning checklist item supplies the current status. These assignments are not
new LOCAL PASS claims: L10 still needs each owning item's final caller,
persistence/restart and acceptance/falsifier reconciliation. Existing historical
evidence is reused where applicable, with changed dependencies checked under L01.

## Economic audit #399

The [requirement-to-caller review](economic-audit-399-pre-nas.md#requirement-to-caller-review)
and [original remediation ledger](economic-audit-399-remediation.md) retain the
source references, original acceptance and provider dispositions for these rows.

| Finding | Requirement | Owner / separate unresolved gate |
| --- | --- | --- |
| F1 | Rounded source-rebase continuity | L05 |
| F2 | Exact share sizing and affordability | L02 |
| F3 | Current-session rename continuity | L05 |
| F4 | Interrupted preparation-job recovery | L08 |
| F5 | Recovery after callback death or terminal execution refusal | L04 |
| F6 | Complete/final cash authority | L03 LOCAL PASS (#424); E1 open |
| F7 | UNKNOWN is not finalized by absent reads | L04 |
| F8 | Capability checks reach nested activity producers | L03 LOCAL PASS (#424) |
| F9 | NAV precision through serialization | L02 |
| F10 | Inclusive stop boundary | L02 |
| F11 | Canonical numeric economic identity | L02; recovery consumer in L04 |
| F12 | Stable notification incident identity | L07 |
| F13 | Notification attempt/owner fencing | L07 |
| F14 | Rolling restore evidence integrity | L06 |
| F15 | Retained action-coverage integrity | L06; economic consumer in L05 |
| F16 | Scoped entitlement price/ownership requirements | L05; fill authority in L03 |
| F17 | Original obligations after shadow advancement | L04 |
| F18 | Planless/adopted command action units | L04; source/action coverage in L05 |
| F19 | Native fill identity, completeness and cumulative notional | L03 LOCAL PASS (#424); E2 open |
| C1 | Accepted cash producer authority and finality | L03 LOCAL PASS (#424); E1 open |
| C2 | Terminal-return economics and schema/version identity | L02 |
| C3 | Predecessor-incarnation recovery completeness | L04 refusal boundary / E3 |

## Autonomy audit #400

The linked comments identify the original finding; their historical open-code
status does not override later fixes. The [chronological closure record](economic-code-closure.md)
retains those fixes, including recurring maintenance, supervisor I/O bounds and
status resource work. Final closure still belongs to the item shown here.

| Original identity | Requirement and extensions | Owner |
| --- | --- | --- |
| [A1](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719693512) | Supervisor/dispatcher database I/O and full stderr pipes cannot prevent deadline enforcement | L07 |
| [A2](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719709967) | Rolling deployment resumes after missed sessions/opens | L08 |
| [A3](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719714701) | Transient PostgreSQL failure/contention does not permanently latch shadow publication | L08 |
| [A4 preparation](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719795587) | Expected job waits, restart leases and publisher death remain recoverable | L08; F4 |
| [A4 alerts](https://github.com/flabber1835/stocker/issues/400#issuecomment-5721512715) | Temporary notification outage does not dead-letter after eight attempts | L07; overlaps notification A6 |
| [A5 WAL](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719837735) | Recurring base rollover bounds the restore horizon | L08 |
| [A5 latch](https://github.com/flabber1835/stocker/issues/400#issuecomment-5721519177) | Shadow integrity latch survives process restart | L08; supervision seam in L07 |
| [A6 notifications](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719842226) | Retry obligations and health recover after transport outage; mixed recipients and endpoint rotation retain ownership | L07 |
| [A6 backups](https://github.com/flabber1835/stocker/issues/400#issuecomment-5721531071) | Unattended recurring backup scheduler exists and converges | L08; overlaps WAL A5 |
| [A7](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719846422) | Idle retention drain reaches the deployed loop | L08 |
| [A8](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719937102) | Settled rejected/expired/cancelled orders do not block later eligible sessions | L04; F5 |
| [A9](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719959880) | Legitimate ticker rename is not classified as historical corruption | L05; F3 |
| [A10](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719975159) | Legitimate rounded rebases preserve continuity | L05; F1 |
| [A11](https://github.com/flabber1835/stocker/issues/400#issuecomment-5719986213) | PostgreSQL statement timeout remains retryable | L08 |
| [A12](https://github.com/flabber1835/stocker/issues/400#issuecomment-5720033308) | Routine status/identity reads meet memory and latency limits | L09; #419 integration in L01 |
| [A13](https://github.com/flabber1835/stocker/issues/400#issuecomment-5720084900) | Fresh authority checks preserve transient-dependency classification | L08 |
| [A14](https://github.com/flabber1835/stocker/issues/400#issuecomment-5720112160) | Recent-SIP entitlement required by the opening path | L05 / E4 |
| [A15](https://github.com/flabber1835/stocker/issues/400#issuecomment-5720179970) | Returning unheld identity after feature retirement | L05 |
| [A16](https://github.com/flabber1835/stocker/issues/400#issuecomment-5720204537) | Held spinoff support or explicit refusal policy | L05 / E4 |
| [A17](https://github.com/flabber1835/stocker/issues/400#issuecomment-5724678401) | Consecutive same-phase invocations receive separate deadlines | L07 |
| [A18](https://github.com/flabber1835/stocker/issues/400#issuecomment-5724719070) | Recurring health incidents and leader replacement preserve alert identity | L07 |
| [A19](https://github.com/flabber1835/stocker/issues/400#issuecomment-5724887290) | Missing control/lease and observation-integrity faults remain externally visible | L07 |
| [A20](https://github.com/flabber1835/stocker/issues/400#issuecomment-5725402714) | Transient PostgreSQL loss at backup guard does not permanently block activation | L08 |
| [A21](https://github.com/flabber1835/stocker/issues/400#issuecomment-5725402939) | Rolling authority admission, preflight, causal session and panel readers; restore-validation extension | L08; restore extension L06; reader resource limit L09 |
| [A22](https://github.com/flabber1835/stocker/issues/400#issuecomment-5725403161) | Dual deployment preserves rolling shadow preparation mode | L08 |
| [A23](https://github.com/flabber1835/stocker/issues/400#issuecomment-5725485189) | Standby is fenced before migration and remains fenced on failure | L08 |
| [A24](https://github.com/flabber1835/stocker/issues/400#issuecomment-5725547610) | Deployment health deadline also bounds the status subprocess | L07; deployment ordering in L08 |
| [A25](https://github.com/flabber1835/stocker/issues/400#issuecomment-5725635342) | Notification enrollment SQL cannot block the HTTP event loop | L07 |
| [A26](https://github.com/flabber1835/stocker/issues/400#issuecomment-5730796219) | Supported installer builds the canonical runtime image | L08 |
| [A27](https://github.com/flabber1835/stocker/issues/400#issuecomment-5734809314) | Retention diagnostic SQL remains inside the maintenance deadline | L08 |

Source: issue body and comments retrieved from GitHub on 2026-09-20. The final
audit also retains 13 unexecuted target-environment scenario families; those stay
under N1 and the named provider gates. Counts of mechanical scans or component
passes do not establish those scenarios or economic certification.
