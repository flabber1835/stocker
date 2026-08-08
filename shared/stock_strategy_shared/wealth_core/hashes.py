"""Wealth Core v1 — the cross-engine parity hashes. PURE.

Seven hashes, computed HERE and nowhere else, so that "the backtester and the
wind tunnel agree" is a fact about one function rather than about two
implementations that happen to round the same way today.

    normalized_input   the VendorBar stream AFTER normalisation
    candidate_audit    every scored candidate, every session
    decision           every operation and rejection, every session
    order              fills and the queue, in execution order
    daily_state        the portfolio state at each session close
    daily_equity       resolved and estimated equity at each session close
    final_result       everything, including the final report

WHY SEVEN AND NOT ONE. A single final hash tells you the runs differ and
nothing else, and on a 260-session run that is close to useless. These are
ordered so that the FIRST one to differ names the layer at fault:

    normalized_input differs  -> the two engines read different DATA. Nothing
                                 downstream is worth looking at.
    candidate_audit differs   -> same data, different eligibility or scoring.
    decision differs          -> same candidates, different rules applied.
    order differs             -> same decisions, different execution.
    daily_state differs       -> same orders, different bookkeeping.
    daily_equity differs      -> same state, different valuation.
    final_result differs      -> only the final report differs.

`first_divergence` walks them in that order and returns the first mismatch,
which is the number an experiment report should lead with.

ROUNDING. Money is rounded to the cent and prices to six decimal places BEFORE
hashing. Two engines can accumulate identical cash flows in a different
association order and land 1e-12 apart; without rounding the parity test fails
forever for a reason that is not a strategy difference, and everyone learns to
ignore it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping, Sequence

# The order that makes a mismatch diagnostic rather than merely true.
HASH_ORDER: tuple[str, ...] = (
    "normalized_input", "candidate_audit", "decision", "order",
    "daily_state", "daily_equity", "final_result",
)


def quantize(o):
    """Round EVERY float in a structure before it is serialised for hashing.

    THE HOLE THIS CLOSES. Several hashes passed `default=` to `json.dumps` and
    rounded floats there. `default` is the hook for objects the encoder CANNOT
    handle, and floats it handles natively — so that rounding never ran, and the
    hashes were taken over raw `repr` output. That made a certified artefact
    depend on the interpreter's float formatting rather than on the strategy.

    Observed on Python 3.13: the state hash, ledger hash, final cash, positions,
    event counts and blocked sessions all matched while `result_hash` differed —
    the signature of an audit-serialisation difference rather than a changed
    portfolio path, which is precisely what a parity artefact must be blind to.

    10 decimal places is far finer than any price, weight or score the engine
    produces, and far coarser than the last bits where formatting differs.
    """
    if isinstance(o, float):
        return round(o, 10)
    if isinstance(o, dict):
        return {k: quantize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [quantize(v) for v in o]
    return o


def _h(payload) -> str:
    return hashlib.sha256(
        json.dumps(quantize(payload), sort_keys=True, separators=(",", ":"),
                   default=str).encode()).hexdigest()


def _canonical(row) -> bytes:
    """One row, in EXACTLY the bytes `_h` would give it inside a list.

    The single place the serialisation options are written for the streaming
    path, so it cannot drift from `_h` by someone changing one and not the
    other.
    """
    return json.dumps(quantize(row), sort_keys=True, separators=(",", ":"),
                      default=str).encode()


class CanonicalListStream:
    """A running sha256 over a JSON list, byte-identical to `_h(list)`, without
    ever holding the list.

    WHY THIS EXISTS. `Decision.candidates` carries one row per eligible
    security per session — ~2000 x 753 = ~1.5 MILLION dicts on a three-year
    certification run, retained because three parity layers hash them. Measured:
    that is the OOM. Bounding diagnostic retention moved peak RSS by 1MB; this
    is where the memory actually is.

    THE MECHANISM, and it is exact rather than approximate. `json.dumps` of a
    list emits `[` + item + `,` + item + ... + `]`, each item serialised with
    the same options. Feeding those bytes to sha256 in order therefore produces
    the identical digest to serialising the whole list at once — so the
    streaming path is not "equivalent", it is the same bytes.

    `hexdigest()` copies the hasher before closing the bracket, so it can be
    read repeatedly without ending the stream.
    """

    __slots__ = ("_hasher", "_n")

    def __init__(self) -> None:
        self._hasher = hashlib.sha256()
        self._n = 0
        self._hasher.update(b"[")

    def add(self, row) -> None:
        if self._n:
            self._hasher.update(b",")
        self._n += 1
        self._hasher.update(_canonical(row))

    def extend(self, rows) -> None:
        for r in rows:
            self.add(r)

    @property
    def rows(self) -> int:
        return self._n

    def hexdigest(self) -> str:
        h = self._hasher.copy()
        h.update(b"]")
        return h.hexdigest()


def _px(x):
    return None if x is None else round(float(x), 6)


def _money(x):
    return None if x is None else round(float(x), 2)


def normalized_input_hash(sessions: Sequence[str],
                          bars_by_session: Mapping[str, Sequence]) -> str:
    """The DATA both engines claim to be running on.

    Deliberately computed from the normalised `VendorBar`s rather than from the
    raw rows: two engines legitimately read different tables in different
    databases, and what has to match is what came OUT of normalisation. A hash
    over raw rows would fail on a column rename that changed nothing.
    """
    payload = []
    for s in sessions:
        rows = sorted(bars_by_session.get(s, ()),
                      key=lambda b: (b.security_id, b.ticker))
        payload.append([s, [[b.security_id, b.ticker, _px(b.raw_close),
                             _px(b.raw_open), _px(b.volume),
                             _px(b.split_ratio), _px(b.dividend_per_share),
                             bool(b.tradeable),
                             bool(b.unresolved_corporate_action)]
                            for b in rows]])
    return _h(payload)


def candidate_audit_hash(result) -> str:
    payload = []
    for s in result.sessions:
        if not s.decision:
            continue
        payload.append([s.session, sorted(
            [[c.security_id, c.ticker, _px(c.momentum), _px(c.recent),
              _px(c.volatility), _px(c.score), bool(c.in_top_decile), c.reason]
             for c in s.decision.candidates])])
    return _h(payload)


def decision_hash(result) -> str:
    return _h([[s.session, s.decision.to_dict()] for s in result.sessions
               if s.decision])


def order_hash(result) -> str:
    """Fills IN EXECUTION ORDER, plus what was cancelled and what is still queued.

    Cancellations are in the hash on purpose: an engine that silently dropped an
    unaffordable order instead of recording it would otherwise match, and the
    difference — a slot left empty for a non-strategy reason — is exactly the
    kind of divergence this is for.
    """
    payload = []
    for s in result.sessions:
        payload.append([s.session,
                        [[f["security_id"], f["operation"], f["shares"],
                          _px(f["raw_open"]), f["waited"]] for f in s.fills],
                        sorted([[c.get("security_id"), c.get("reason"),
                                 c.get("wanted_shares"), c.get("filled_shares")]
                                for c in s.cancelled])])
    payload.append(["__unfilled__", sorted(
        [[o["security_id"], o["operation"], o["shares"], o["sessions_waiting"]]
         for o in result.unfilled_at_end])])
    return _h(payload)


def daily_state_hash(result) -> str:
    """Per-session state hashes, not just the final one.

    Two runs can end in identical state having taken different paths — an exit
    and a re-entry versus a hold — and the daily sequence is what distinguishes
    them. It is also what makes `first_divergence` able to name a SESSION.
    """
    return _h([[s.session, s.decision.input_state_hash]
               for s in result.sessions if s.decision])


def daily_equity_hash(result) -> str:
    return _h([[s.session, _money(s.resolved_equity),
                _money(s.estimated_equity), bool(s.blocked)]
               for s in result.sessions])


def final_result_hash(result) -> str:
    return result.result_hash()


_COMPUTERS = {
    "candidate_audit": candidate_audit_hash,
    "decision": decision_hash,
    "order": order_hash,
    "daily_state": daily_state_hash,
    "daily_equity": daily_equity_hash,
    "final_result": final_result_hash,
}


@dataclass(frozen=True)
class ParityHashes:
    values: dict

    def to_dict(self) -> dict:
        return dict(self.values)

    def __getitem__(self, k):
        return self.values[k]


def parity_hashes(result, sessions: Sequence[str],
                  bars_by_session: Mapping[str, Sequence]) -> ParityHashes:
    out = {"normalized_input": normalized_input_hash(sessions, bars_by_session)}
    for name, fn in _COMPUTERS.items():
        out[name] = fn(result)
    return ParityHashes(values=out)


def first_divergence(a: ParityHashes | Mapping,
                     b: ParityHashes | Mapping) -> str | None:
    """The FIRST layer at which two runs differ, in diagnostic order.

    Returns None when every hash matches. Callers should report this rather than
    a list of mismatches: once `normalized_input` differs, every later hash
    differing is a consequence, and listing all seven invites someone to debug
    the ranking when the real problem is that one engine read a different table.
    """
    av = a.values if isinstance(a, ParityHashes) else dict(a)
    bv = b.values if isinstance(b, ParityHashes) else dict(b)
    for name in HASH_ORDER:
        if av.get(name) != bv.get(name):
            return name
    return None


def divergence_report(a, b, *, left: str = "left", right: str = "right") -> dict:
    av = a.values if isinstance(a, ParityHashes) else dict(a)
    bv = b.values if isinstance(b, ParityHashes) else dict(b)
    first = first_divergence(a, b)
    return {
        "identical": first is None,
        "first_divergence": first,
        "interpretation": _INTERPRETATION.get(first),
        "hashes": {name: {left: av.get(name), right: bv.get(name),
                          "match": av.get(name) == bv.get(name)}
                   for name in HASH_ORDER},
    }


_INTERPRETATION = {
    "normalized_input": "the two engines read different DATA; nothing "
                        "downstream is worth investigating until this matches",
    "candidate_audit": "same data, different eligibility or scoring",
    "decision": "same candidates, different rules applied",
    "order": "same decisions, different execution or fill handling",
    "daily_state": "same orders, different bookkeeping",
    "daily_equity": "same state, different valuation",
    "final_result": "only the final report differs",
}


__all__ = ["HASH_ORDER", "quantize", "ParityHashes", "divergence_report", "first_divergence",
           "parity_hashes"]
