# Certification claim coverage

Date: 2026-09-06. Examined certificate: run 34014048220, source `27bb992087182c42c3c051e62bf837895f5d2ab7`, certificate hash `e769073eaf63573010c00785479e65e35fa397b7bb5204e79525a3519b058cf5`.

The retained certificate is preserved. This audit places its use as proof of the intended Champion economics on hold.

## What the existing certificate does establish

The workflow completed, consumed an identified canonical package, retained a source closure and runtime identity, produced a complete measured daily path, and passed its configured tests and finalizer predicates. The source and dataset identities are concrete reproducibility evidence.

The certificate configuration names the Champion parameters, source, runtime, dates and terminal-grace flag. Initial capital, participation semantics and dividend lag are recoverable from source; they are not enumerated as named economic parameters in that configuration. This is an explicit-contract deficiency, not a claim that the whole Git commit is cryptographically unbound.

## Gap 1: financial-semantics label validates declarations

At the exact certified source, `backtester/certify_backtest_result.py:collect_replay_evidence` computes `financial_ok` from three metadata values:

- requires_resolved_nav is truthy;
- missing_leadership_return_policy equals FAIL_CLOSED;
- dividend_lag_sessions equals 15.

That collector does not independently reconstruct portfolio cash, shares, dividend entitlement, or open/close NAV. Its financial label therefore verifies the declared convention and associated metadata, not complete accounting correctness.

The 15-session convention is clearly an intentional requirement of this finalizer and the freeze document. The unresolved specification question concerns whether this formal-certification derivative is the intended economic contract for the original research Champion/production-parity claim. It must not be described as an undocumented numerical accident.

## Gap 2: checkpoint label is supplied as PASS

The collector's `checkpoint_resume` argument defaults to PASS. The actual certified workflow supplies `--checkpoint-resume PASS` to both replay-evidence and test-evidence collection. The resulting certificate records `annual_chain: null`.

No independently verified full-state resume chain for this generated Champion is established by those flags. Generic production checkpoint tests and exact-Champion path equivalence are different claims.

## Reproduced collector fixture

The exact collector was called with the original valid experiment identity and only two newly created fixture files:

1. summary.json declaring PASS and the expected dataset hash;
2. metadata_authority_audit.json declaring the three financial conventions and an empty list of economically active current-TICKERS fields.

No historical replay, accounting ledger, checkpoint, fill file or daily curve was supplied. The collector returned PASS for financial_semantics and checkpoint_resume, along with the other collected flags; annual_chain remained null.

This test concerns the **collector**, not the complete finalizer. It does not demonstrate that a fabricated full PIT certificate can pass all independent finalizer inputs. It demonstrates that these particular labels do not carry the economic and restart proof implied by their names.

Reproducer: `backtester/champion_certification_claim_probe.py`.

Exact source-file SHA256: `e6af5674a34c3fc1d856aed343199d71ada04dc6db8fad2bed0507799b3afd10`.

Recorded local unit execution: CPython 3.13.5; the original certificate runtime is CPython 3.12.14. The reproducer takes the exact source and original identity as explicit inputs, reports its executing Python version, and can run in the pinned environment. This local fixture is not substituted for the pinned historical replay.

## Gap 3: dynamic causality tests execute a different economic program

`backtester/future_leak_certification_pinned_runtime.py` imports pinned `sentinel.core.production`, aliases `advance_state` as `advance_session`, and exposes that module through the kernel/session imports used by the future-leak suite.

The retained dynamic report contains annual deterministic probes and five cold-start real-kernel epochs (2006, 2011, 2016, 2021 and 2026), each bounded to at most 141 sessions. Its future-poison/truncation evidence is useful for that adapter/kernel scope.

It does not invoke the generated research Champion program whose participation guard, classifier, dividend posting and Native/CandidateA overlay produced the reported CAGR. Exact equivalence between those economic programs is already contradicted by the semantic diff. The statement that dynamic tests proved this exact research replay is consequently too broad.

## Gap 4: identity and accounting completeness are distinct

A correct source hash identifies the code that ran. It does not prove that a declared economic rule is intended or correctly implemented. A cash/share/receivable ledger can reconcile even when the current ex-date receivable is absent from the open allocation witness. The independent open-entitlement probe exposes precisely that distinction.

Similarly, a historical classification can be factually accurate while its declared evidence-availability date is later than the session in which the classifier applies it. The PDS probe demonstrates the actual code's missing availability check.

## Required correction to the evidence contract

Final certification must join results from the **exact generated Champion program and effective economic configuration**. The financial proof must include independent entitlement-complete open and close NAV, signed cash/share transitions, known and proxy terminal claims, and explicit costs. Resume proof must compare uninterrupted and resumed complete state, including pending orders, cash, receivables, split/terminal state, price/volume histories, ranking histories and every controller.

Negative controls must fail for reintroduced whole-order capacity deferral, delayed ex-date claim posting at the open boundary, future-dated classification authority, and altered resumed state. Passing a metadata predicate is not sufficient evidence for those economic properties.

These are bounded proof obligations for the existing implementation and frozen strategy. They do not authorize a strategy redesign or production promotion.
