"""New snapshots use the unchanged qualified whole-ledger evaluator."""
from copy import deepcopy


def need(value, code):
    if not value:
        raise ValueError('REFUSED_P01_NATIVE_ACCOUNTING_' + code)


class AccountingCursor:
    """Bind old prefixes; never create a new numerical accounting origin."""
    def __init__(self, parent, quote, actions, *, evaluator=None):
        if evaluator is None:
            from p01_factual_batch_accounting import reconcile
            evaluator = reconcile
        self.old_events = deepcopy(parent['run']['state']['ledger']['events'])
        self.previous_events = self.old_events
        self.parent_state = deepcopy(parent['run']['state'])
        self.quote, self.actions, self.evaluator = quote, actions, evaluator
        self.snapshots = 0
        self.last = None

    def reconcile(self, snapshot):
        events = snapshot['ledger']['events']
        need(type(events) is list and len(events) >= len(self.previous_events)
             and events[:len(self.old_events)] == self.old_events
             and events[:len(self.previous_events)] == self.previous_events,
             'ENTIRE_ADMITTED_AND_NEW_LEDGER_PREFIX_UNCHANGED')
        before = deepcopy(snapshot)
        # Preserve the exact prior evaluator, including its initial capital,
        # Decimal accumulation, tolerances, right quote and binary64 cash checks.
        proof = self.evaluator(snapshot, self.quote, self.actions)
        need(snapshot == before, 'READ_ONLY_COMPLETE_SNAPSHOT_AND_LEDGER')
        self.previous_events = deepcopy(events)
        self.snapshots += 1
        self.last = proof
        return proof

    def result(self):
        return dict(new_ledger_events=len(self.previous_events) - len(self.old_events),
                    new_accounting_snapshots=self.snapshots, old_accounting_snapshots_recomputed=0,
                    old_snapshot_replays=0, whole_ledger_evaluator_unchanged=True,
                    accounting_origin_reset=False, numerical_tolerances_changed=False,
                    entire_old_ledger_prefix_unchanged=True, last_accounting_proof=self.last)
