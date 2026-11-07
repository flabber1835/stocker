# P06 FIN339 private readonly recovery, frozen runtime delivery

Copy the two new modules and their two source assets to capital_risk:
system_campaign_p06_fin339_readonly_recovery.py,
system_campaign_p06_BBIG_accounting_review.py,
P06-FIN339-readonly-recovery-fact.json and
P06-FIN339-captured-financial-request.json. Preserve every existing module.
Install P06-FIN339-failed-review-target.json as only the P06 partial target;
leave admitted1383/full10 root28c768... unchanged. New target remains failed0/1/1.

Choose one explicit readonly request (financial0/readonly1), P06 only, through
READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION. In the bounded lifecycle
dispatch source_names, add recovery.source_names(); in expected_request, wrap
the existing result with recovery.expected_request, passing execution_mode,
selected_arms and the existing partial target lookup. The new declaration field
must be present and exact; original financial declaration remains unselected.

At the beginning of lifecycle dispatch entry_context, before legacy full10 or
financial fallbacks, if recovery.selected_request(request) then enter
recovery.context(request,spec=spec,mode=mode,module=module,old=old,out=out,
evidence=evidence) and yield/return. This handles only launch, preflight and
review, refuses economic. The launcher has no common entry dispatch; append
launch=recovery.bind_launch(launch) at the bottom of financial_resume, after
existing wrappers and before __main__. Complete original four m bodies stay.
Do not wrap readonly modes through financial v3 or switch request to financial.

Original launch authenticates failed transport via unchanged quarantine reader,
performs readonly accounting/monthly preflight, mounts genuine admitted1383 as
/old and genuine actual1426 as /evidence, and runs original full review once.
The new review namespace retains all original130-to173 proof and neutral11
guards, uses the real ABMD InputCodec and complete input history, and lifts only
two published compact-accounting DTO arguments to the original source guard.
runtime.run remains financially guarded and outer context forbids economic.

Require a fresh positive repair_reviewer, core1426, branch43+130, BBIG combined
source review and original monthly reproduction in the separate readonly
artifact. Existing failed receipt and transport are immutable; qualify the new
artifact independently before any admission. No financial continuation or new
root is selected by this package. Independent saved-result DATA is a separate
pending deliverable and must not be claimed complete from local tests.

Local tests use only authenticated data, source/AST, explicit noncanonical
review DTOs and metadata hook mocks. They do not restore checkpoints or call
MonthlyStats/the financial engine. The actual source_record failure is
reproduced, then the unchanged source_record passes on correctly expanded
actual DTOs. Two meaningful guard-removal falsifiers and five import fences
pass. Frozen runtime delivery must not be edited to satisfy integration tests;
send findings back for a finite version instead.
