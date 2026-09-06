#!/usr/bin/env python3
"""Bounded factual type corrections over the pinned reviewed-18/PDS/EQM layer."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from backtester import research_champion_corrected_classification as prior
from backtester.champion_security_truth_audit_v2 import load_cases, FACTS_SHA256, DEFAULT_FACTS

ACTIVE_ESTIMATES = []


class SecurityTypeEstimate(prior.SecurityTypeEstimate):
    def __init__(self, ledger: Path, scenario: str):
        super().__init__(ledger, scenario)
        self.fact_document, self.factual_cases = load_cases(DEFAULT_FACTS, self.rows)
        self.factual_calls = Counter()
        ACTIVE_ESTIMATES.append(self)

    def _classify(self, security_id: str, session: str, *, count: bool) -> str:
        sid, session = str(security_id), str(session)
        if sid not in self.factual_cases:
            return super()._classify(sid, session, count=count)
        case = self.factual_cases[sid]
        if not case['effective_first_session'] <= session <= case['effective_last_session']:
            raise RuntimeError(f'factual correction requested outside admitted interval: {sid} {session}')
        if super()._classify(sid, session, count=False) != case['previous_classification']:
            raise RuntimeError(f'factual correction baseline has changed: {sid} {session}')
        result = case['classification']
        if count:
            self.calls[result] += 1
            self.factual_calls[sid] += 1
        return result

    def provenance(self, security_id: str, session: str) -> dict[str, str]:
        sid = str(security_id)
        if sid not in self.factual_cases:
            return super().provenance(sid, session)
        self._classify(sid, session, count=False)
        case = self.factual_cases[sid]
        return {'source_status': 'REVIEWED_FACTUAL_TYPE_CORRECTION_NOT_FULL_CERTIFICATION',
                'effective_first_session': case['effective_first_session'], 'effective_last_session': case['effective_last_session'],
                'evidence_kind': case['legal_security_type'], 'evidence_source_ids': '|'.join(case['source_ids']),
                'evidence_timing_policy': self.fact_document['evidence_timing_policy'],
                'factual_batch_sha256': FACTS_SHA256}

    def summary(self) -> dict:
        result = super().summary()
        result.update(label='PARTIAL_FACTUAL_AUDIT_NOT_CERTIFIED', factual_batch_sha256=FACTS_SHA256,
                      factual_correction_calls=dict(sorted(self.factual_calls.items())), certification_eligible=False)
        return result

# Read-only observer receives only copied tuples of string IDs from the engine.
PATH_COUNTS = {}
PATH_SESSIONS = []


def observe(session: str, durable: tuple, held: tuple, pending: tuple, leadership: tuple, eligible: tuple) -> None:
    if len(ACTIVE_ESTIMATES) != 1:
        raise RuntimeError('fresh path observer requires exactly one classifier instance')
    for values in (durable, held, pending, leadership, eligible):
        if not isinstance(values, tuple) or any(not isinstance(sid, str) for sid in values):
            raise TypeError('path observer accepts copied string-ID tuples only')
    if PATH_SESSIONS and session <= PATH_SESSIONS[-1]:
        raise RuntimeError('path observer sessions must be strictly increasing')
    PATH_SESSIONS.append(session)
    admitted = ACTIVE_ESTIMATES[0].rows
    for key, values in [('durable_ranked_sessions', durable), ('held_sessions', held), ('pending_sessions', pending),
                        ('recent_leadership_sessions', leadership), ('eligible_sessions', eligible)]:
        if not isinstance(values, tuple) or any(not isinstance(sid, str) for sid in values):
            raise TypeError('path observer accepts copied string-ID tuples only')
        for sid in set(values):
            if sid in admitted:
                PATH_COUNTS.setdefault(sid, Counter())[key] += 1
