# Stage 1 L04 recovery closeout

Reviewed production base: `daa43caf995779bfa7e67195785520744021cb45`.
This acceptance campaign joins the previously separate F5/F7/F17 process-death,
negative-read and historical-shadow tests. It changes no production policy.

The missing compound case is a broker acceptance followed by SIGKILL, before or
after the acknowledgement commit. A fresh PostgreSQL connection must retain the
original command, repeated absent reads must not finalize it, and the public
executor must refuse replacement. Test both the original shadow close and a newer
published close. Positive original-order evidence must then converge through PAPER
recovery, survive another connection restart, and describe exactly ten shares and
one $1,000 purchase at the simulator's stipulated $100 price.

Use real journal commits, retained rolling publications, plan lookup, recovery,
and reconciliation. Signed certificate issuance and automation grant validation
remain explicit fixture boundaries; this does not qualify deployed authority.
The simulated broker's accepted state survives the killed sender in a retained
test-only snapshot and is loaded into a new object. It establishes contract
behavior, not provider finality. After the empty reads, a separately specified
20-share successor contract target must also be blocked; an adopted control
generation then observes the original ten-share fill without executing that
successor target.

Local validation: 48 regression cases passed; after strengthening the takeover
fixture, three overlapping targeted controls passed and all six deliberate
regressions were detected at the intended contract checks. Exact commands, failed
fixture attempts and source-bound artifacts are retained in
[the evidence package](../audit/economic_399/recovery_closeout/README.md).
**L04 local disposition: LOCAL PASS on the reviewed base; integration remains L01.**
C3 predecessor completeness remains blocked; keep STRICT_V1 and its takeover
fence. No provider capability is enabled by this campaign.

## Finding-to-caller and persistence map

Line references below describe the reviewed base; function names are stable
navigation anchors. The links point to source, not to a substitute implementation.

| Finding | Production caller and persistence/restart | Acceptance and falsifier |
| --- | --- | --- |
| F5 / A8 | [`executor._persist_and_send`](../sentinel/execution/executor.py) (802) commits PLANNED and SEND_PENDING before dispatch through [`journal.save_command`](../sentinel/execution/journal.py) (509). [`AutomationService._handle_callback_failure`](../sentinel/automation/service.py) (467) keeps EXECUTE failures in RECONCILING; [`RecoveryAutomationService`](../sentinel/automation_resilience.py) (81) does the same for a killed deadline. `ProductionAutomation.recover` in [`automation_runtime.py`](../sentinel/automation_runtime.py) (923) preserves in-flight obligations, then supersedes settled historical/refused intent. Cycle state/events and command state/events persist separately. | `test_execution_callback_death.py` covers real SIGKILL before/after acknowledgement and a durable next wake; `test_newly_rejected_submit_requires_read_only_recovery` covers terminal refusal routing. The new four-case compound test requires pre-send durability; `send-before-durable-pending` removes that write. |
| F7 | [`reconcile.reconcile`](../sentinel/execution/reconcile.py) (745â€“901) persists SEND_PENDING promotion, preserves UNKNOWN on absent evidence, and only learns positive account-bound order facts. The public [`executor.execute_session`](../sentinel/execution/executor.py) (397) returns before sizing/submission while RECONCILING. The separate boot caller [`resolve_outstanding`](../sentinel/execution/executor.py) (841) uses [`recovery.resolve_unknown`](../sentinel/execution/recovery.py) (236), whose absent result also remains UNKNOWN. | Compound test: three fresh-connection absent-read cycles, successor submission refusal, original key/quantity retained, one eventual fill. `test_unknown_absence_finality.py` and `test_p0_recovery_and_staleness.py` also cover the boot route and stale-plan refusal. `absence-as-terminal` manufactures cancellation; `forget-positive-fill-commit` removes restart durability. |
| F17 | [`paper.recover_automated_paper_cycle`](../sentinel/paper/recovery.py) (219â€“240) binds only the matching generation's plan, then drops its target interpretation if the current shadow frontier is later. Recovery still reads the original durable commands. `automation_runtime.py` (1027) supersedes the historical cycle only after its obligations settle. | Existing historical recovery checks ACKNOWLEDGED and FILLED under current/adopted generations. New compound cases cross SIGKILL, empty reads and a later actual rolling publication. `reinterpret-old-shadow-target` removes the historical-target exclusion and must fail with the different-close refusal. |
| F18 | [`paper.targets._action_lookup`](../sentinel/paper/targets.py) (75) includes the earliest durable command date even with no current plan/state. [`expected_book_from_commands`](../sentinel/execution/reconcile.py) (428) ages each command from its own basis through retained action evidence. Filled native quantities are not rewritten to today's units. | `test_planless_action_units.py`: held and fully exited equity/BIL through retained 2x then 3x events; ten native shares imply sixty current shares (or zero after the recorded sale). `forget-command-action-basis` substitutes the later boundary and loses the sixfold units. |
| C3 | [`recovered_order_policy`](../sentinel/execution/recovered_order_policy.py) (33, 67) rejects unauthenticated prefix-only orders and prevents Alpaca recovery-watermark advancement at takeover epoch >1. Both [`automation`](../docker-compose.sentinel-automation.yml) (17) and [`standby`](../docker-compose.sentinel-automation-standby.yml) (26) set STRICT_V1. Durable binding epoch, command preimage and terminal watermark have distinct roles. | Fresh-interpreter `test_strict_recovery_predecessor.py` covers prefix refusal and restored epoch. Its nonempty positive control earns a real completion witness before takeover; after restart, the otherwise valid successor observation cannot advance the watermark. `remove-predecessor-fence` then fails at the intended assertion. `test_recovery_capability_boundary.py` keeps unaccepted nested activity history quarantined. This is local refusal-boundary acceptance, **not C3 completeness acceptance**. |

The new test does not mock journal, reconciliation, target-age selection or
executor blocking. Its ten-share/$1,000 oracle is a stipulated economic example,
not a second execution of the strategy under test. The 20-share successor is
only a lower execution-contract input; it is not asserted to be Wealth Core's
desired portfolio. Real certificate issuance, lease takeover, production broker
history and native fill accounting remain outside this simulator acceptance.

## Remaining gates and handoff

- **C3 / E3, P1:** missing provider-backed predecessor interval completeness,
  authenticated command preimages and an accepted recovery protocol. The guard
  at `recovered_order_policy.py:75` stays closed; no amount of repeated empty
  reads supplies the missing evidence.
- **L01, integration pending:** #419 changes shadow storage and #421 changes
  cash dependencies. Neither changes these command-recovery modules, but this
  main-based result is not a passing combined-tree claim. Recheck the compound
  acceptance when those dependencies are owner-merged.
- **N1, deployed evidence:** after separate NAS authorization, exercise process
  loss/reboot in an isolated account-free qualification stack built from the
  accepted image/schema. Retain command/event rows before death, cycle recovery
  wake and lease history, broker-simulator acceptance identity, post-restart
  observation rows, one original fill and zero replacement submissions. Both
  crash cuts and same/new shadow-close cases must converge. Missing obligations,
  terminalization from absence, a new key or altered shares/cash is failure.
  Keep actual provider-account qualification separate and retain the C3 fence.

For full deployment prerequisites and commands, retain the existing
[NAS handoff](economic-audit-399-pre-nas.md); this follow-up does not authorize
NAS operations or close its provider and host gates.
