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


class CanonicalArraySpool:
    """Canonical JSON array bytes, SPOOLED so they can be replayed later.

    A DIFFERENT PRIMITIVE FROM CanonicalListStream, deliberately. That one is a
    running digest and can never give its bytes back, which is exactly right for
    a standalone hash and useless for `final_result_hash`.

    `result_hash` hashes an OBJECT, so under `sort_keys=True` the sessions array
    sits at a fixed position among alphabetically ordered keys. Reproducing the
    identical digest means feeding `pre + [rows] + post` to one hasher — but
    `pre` contains the FINAL STATE and is unknown until the run ends. So the
    session bytes must outlive the sessions that produced them.

    THE INSIGHT THIS ENCODES: the bytes must survive long enough to reach the
    hash; they do NOT need to survive in RAM. They are written once, sequentially,
    and read back once, sequentially — the access pattern a file is best at.

    `SpooledTemporaryFile` keeps short runs entirely in memory and only spills to
    disk past `max_ram_bytes`, so the golden fixture and every debug run pay no
    IO at all while a 753-session certification stays bounded.

    Not reusable after `close()`, and `add` after close raises: a spool that
    silently accepted rows after its bracket was written would produce malformed
    JSON bytes and a plausible, permanently wrong certification hash.
    """

    #: 32MB. Far above any short or golden run, far below the ~1.5M candidate
    #: rows a three-year certification produces.
    DEFAULT_MAX_RAM = 32 * 1024 * 1024

    def __init__(self, max_ram_bytes: int | None = None) -> None:
        import tempfile
        self._f = tempfile.SpooledTemporaryFile(
            max_size=(self.DEFAULT_MAX_RAM if max_ram_bytes is None
                      else max_ram_bytes))
        self._n = 0
        self._closed = False
        self._f.write(b"[")

    def add(self, row) -> None:
        if self._closed:
            raise RuntimeError(
                "CanonicalArraySpool is closed; adding a row now would append "
                "after the array's closing bracket and produce malformed bytes")
        if self._n:
            self._f.write(b",")
        self._n += 1
        self._f.write(_canonical(row))

    def extend(self, rows) -> None:
        for r in rows:
            self.add(r)

    @property
    def rows(self) -> int:
        return self._n

    @property
    def spilled_to_disk(self) -> bool:
        """True once the spool exceeded its RAM budget. Reported by the scale
        test so 'bounded memory' is observed rather than assumed."""
        return getattr(self._f, "_rolled", False)

    def close(self) -> None:
        if not self._closed:
            self._f.write(b"]")
            self._closed = True

    def replay_into(self, hasher, chunk: int = 1 << 20) -> None:
        """Feed the array's bytes to `hasher`, in order, without loading them."""
        self.close()
        self._f.seek(0)
        while True:
            b = self._f.read(chunk)
            if not b:
                break
            hasher.update(b)

    def hexdigest(self) -> str:
        """Standalone digest — identical to `_h(list_of_rows)`."""
        h = hashlib.sha256()
        self.replay_into(h)
        return h.hexdigest()

    def dispose(self) -> None:
        try:
            self._f.close()
        except Exception:      # pragma: no cover - best effort cleanup
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.dispose()
        return False


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
    # STREAMED, one session at a time. Materialising this built the ENTIRE bar
    # stream as one nested list before hashing — 6.6M bars on a three-year
    # certification, several GB in a single transient, and the largest
    # run-length term left after the candidate payload was folded. The digest is
    # byte-identical; only the peak changes.
    stream = CanonicalListStream()
    for s in sessions:
        rows = sorted(bars_by_session.get(s, ()),
                      key=lambda b: (b.security_id, b.ticker))
        stream.add([s, [[b.security_id, b.ticker, _px(b.raw_close),
                         _px(b.raw_open), _px(b.volume),
                         _px(b.split_ratio), _px(b.dividend_per_share),
                         bool(b.tradeable),
                         bool(b.unresolved_corporate_action)]
                        for b in rows]])
    return stream.hexdigest()


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


class SessionHashAccumulator:
    """The six session-derived parity hashes, folded ONE SESSION AT A TIME.

    This is what lets a certification run discard `Decision.candidates` — one
    row per eligible security per session, ~1.5 MILLION dicts over a three-year
    run, and measured as the reason the rehearsal OOMs. Each session is folded
    here and then dropped; the digests are byte-identical to hashing the whole
    retained list at the end, because CanonicalListStream and
    CanonicalArraySpool reproduce `json.dumps` of a list exactly.

    `order` carries a trailing `__unfilled__` row that belongs after every
    session, so it is appended at `finalize` rather than during the fold.
    """

    def __init__(self, spool_max_ram: int | None = None) -> None:
        self.candidate_audit = CanonicalListStream()
        self.decision = CanonicalListStream()
        self.order = CanonicalListStream()
        self.daily_state = CanonicalListStream()
        self.daily_equity = CanonicalListStream()
        # The sessions array for `final_result`, which is spliced into an
        # OBJECT and therefore needs its bytes back — see CanonicalArraySpool.
        self.sessions = CanonicalArraySpool(max_ram_bytes=spool_max_ram)

    def add(self, s, session_row: dict) -> None:
        """Fold one session. `session_row` comes from `RunResult.session_row`
        so the materialised and streamed paths cannot describe different
        structures."""
        if s.decision:
            self.candidate_audit.add([s.session, sorted(
                [[c.security_id, c.ticker, _px(c.momentum), _px(c.recent),
                  _px(c.volatility), _px(c.score), bool(c.in_top_decile),
                  c.reason]
                 for c in s.decision.candidates])])
            self.decision.add([s.session, s.decision.to_dict()])
            self.daily_state.add([s.session, s.decision.input_state_hash])
        self.order.add([s.session,
                        [[f["security_id"], f["operation"], f["shares"],
                          _px(f["raw_open"]), f["waited"]] for f in s.fills],
                        sorted([[c.get("security_id"), c.get("reason"),
                                 c.get("wanted_shares"), c.get("filled_shares")]
                                for c in s.cancelled])])
        self.daily_equity.add([s.session, _money(s.resolved_equity),
                               _money(s.estimated_equity), bool(s.blocked)])
        self.sessions.add(session_row)

    def finalize(self, result, sessions: Sequence[str],
                 bars_by_session: Mapping[str, Sequence]) -> "ParityHashes":
        self.order.add(["__unfilled__", sorted(
            [[o["security_id"], o["operation"], o["shares"],
              o["sessions_waiting"]] for o in result.unfilled_at_end])])
        return ParityHashes(values={
            "normalized_input": normalized_input_hash(sessions, bars_by_session),
            "candidate_audit": self.candidate_audit.hexdigest(),
            "decision": self.decision.hexdigest(),
            "order": self.order.hexdigest(),
            "daily_state": self.daily_state.hexdigest(),
            "daily_equity": self.daily_equity.hexdigest(),
            "final_result": result.result_hash_spliced(self.sessions),
        })

    def dispose(self) -> None:
        self.sessions.dispose()


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
