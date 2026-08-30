"""Strict loader for frozen research-only terminal settlement terms.

The dataset contains historical corporate-action economics only.  It carries no
strategy holdings, decisions, allocations, trades, or NAV path.  Production's
``TerminalTerms`` remains the only type that can reach Wealth Core.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Mapping, Sequence

SCHEMA = "backtester.causal-terminal-terms/1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FrozenTerminalTermsError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _positive(value) -> bool:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x) and x > 0.0


def _nonnegative(value) -> bool:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x) and x >= 0.0


def _expected_digest(checksum_path: Path, data_path: Path) -> str:
    lines = [line.strip() for line in checksum_path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if len(lines) != 1:
        raise FrozenTerminalTermsError(
            f"{checksum_path}: expected exactly one checksum row")
    parts = lines[0].split()
    if len(parts) != 2:
        raise FrozenTerminalTermsError(
            f"{checksum_path}: malformed checksum row")
    digest, name = parts
    name = name.lstrip("*")
    if not _SHA256.fullmatch(digest) or name != data_path.name:
        raise FrozenTerminalTermsError(
            f"{checksum_path}: checksum target/digest is invalid")
    return digest


def _require_text(row: Mapping, field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise FrozenTerminalTermsError(f"terminal row has invalid {field!r}")
    return value.strip()


def load_frozen_terminal_terms(
    data_path: Path,
    checksum_path: Path,
    *,
    sessions: Sequence[str],
    resolve_identity,
    meta: Mapping[str, object],
    TerminalTerms,
    TerminalKind,
    identity_binding: str = "frozen",
) -> tuple[dict[str, tuple[object, ...]], str]:
    """Load, validate, and instantiate exact production ``TerminalTerms``.

    ``identity_binding='frozen'`` preserves the original certification behavior:
    the replay resolver must reproduce the security IDs stored in the evidence
    bundle exactly.

    ``identity_binding='resolved'`` is for strict-PIT replays whose causal
    security IDs deliberately differ from legacy Sharadar permanent IDs.  The
    frozen ticker/session remains the causal join key, the replay resolver
    supplies the economically active ID, and the frozen ID is retained only in
    the TerminalTerms reference for provenance.
    """
    if identity_binding not in {"frozen", "resolved"}:
        raise FrozenTerminalTermsError(
            f"unsupported terminal identity binding: {identity_binding!r}")

    expected = _expected_digest(checksum_path, data_path)
    observed = sha256_file(data_path)
    if observed != expected:
        raise FrozenTerminalTermsError(
            f"causal terminal terms checksum mismatch: {observed} != {expected}")

    try:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrozenTerminalTermsError(
            f"cannot parse causal terminal terms: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise FrozenTerminalTermsError(
            f"unexpected causal terminal terms schema: {payload.get('schema')!r}")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise FrozenTerminalTermsError("causal terminal terms contain no records")

    session_set = set(map(str, sessions))
    if not session_set:
        raise FrozenTerminalTermsError("replay session axis is empty")
    first_session = min(session_set)
    last_session = max(session_set)
    seen: set[tuple[str, str]] = set()
    by_session: dict[str, list[object]] = {}

    for raw in records:
        if not isinstance(raw, dict):
            raise FrozenTerminalTermsError("terminal record must be an object")
        frozen_sid = _require_text(raw, "security_id")
        ticker = _require_text(raw, "ticker")
        session = _require_text(raw, "effective_session")
        known_by = _require_text(raw, "known_by")
        reference = _require_text(raw, "reference")
        kind_text = _require_text(raw, "kind")
        if known_by > session:
            raise FrozenTerminalTermsError(
                f"terminal event {frozen_sid} uses future-known evidence: {known_by} > {session}")
        # The frozen bundle spans a longer historical horizon than every replay.
        # Events wholly before/after the active replay are valid provenance but
        # cannot affect this run and therefore do not need an identity on its axis.
        if session < first_session or session > last_session:
            continue
        # A dated event inside the active calendar window must land on an actual
        # replay session; silently shifting an in-window event would alter economics.
        if session not in session_set:
            raise FrozenTerminalTermsError(
                f"terminal event {frozen_sid} is dated off the replay session axis: {session}")

        resolved = resolve_identity(ticker, session)
        if resolved is None:
            raise FrozenTerminalTermsError(
                f"frozen terminal identity unresolved for {ticker} {session}")
        resolved_sid = str(resolved)
        if identity_binding == "frozen":
            if resolved_sid != frozen_sid:
                raise FrozenTerminalTermsError(
                    f"frozen terminal identity mismatch for {ticker} {session}: "
                    f"expected {frozen_sid}, resolved {resolved_sid!r}")
            sid = frozen_sid
            if sid not in meta:
                raise FrozenTerminalTermsError(
                    f"frozen terminal security {sid} has no replay metadata")
        else:
            sid = resolved_sid

        key = (session, sid)
        if key in seen:
            raise FrozenTerminalTermsError(
                f"duplicate frozen terminal terms for {sid} on {session}")
        seen.add(key)

        sources = raw.get("sources")
        if (not isinstance(sources, list) or not sources
                or any(not isinstance(item, str) or not item.startswith("https://")
                       for item in sources)):
            raise FrozenTerminalTermsError(
                f"frozen terminal record {frozen_sid} lacks auditable HTTPS sources")

        try:
            kind = TerminalKind(kind_text)
        except Exception as exc:
            raise FrozenTerminalTermsError(
                f"unsupported terminal kind {kind_text!r} for {frozen_sid}") from exc

        provenance_prefix = "research/causal-terminal-terms-v1 "
        if identity_binding == "resolved" and sid != frozen_sid:
            provenance_prefix += f"frozen_security_id={frozen_sid} "
        kwargs = {
            "session": session,
            "security_id": sid,
            "kind": kind,
            "reference": provenance_prefix + reference,
        }
        if kind_text == "CASH_MERGER":
            cash = raw.get("cash_per_share")
            if not _nonnegative(cash):
                raise FrozenTerminalTermsError(
                    f"cash merger {frozen_sid} has invalid cash_per_share {cash!r}")
            kwargs["cash_per_share"] = float(cash)
        elif kind_text in {"CONVERSION", "CASH_PLUS_STOCK"}:
            frozen_delivered_sid = _require_text(raw, "delivered_security_id")
            delivered_ticker = _require_text(raw, "delivered_ticker")
            delivered_resolved = resolve_identity(delivered_ticker, session)
            if delivered_resolved is None:
                raise FrozenTerminalTermsError(
                    f"delivered identity unresolved for {delivered_ticker} {session}")
            delivered_sid = str(delivered_resolved)
            if identity_binding == "frozen":
                if frozen_delivered_sid not in meta:
                    raise FrozenTerminalTermsError(
                        f"delivered security {frozen_delivered_sid} has no replay metadata")
                if delivered_sid != frozen_delivered_sid:
                    raise FrozenTerminalTermsError(
                        f"delivered identity mismatch for {delivered_ticker} {session}: "
                        f"expected {frozen_delivered_sid}, resolved {delivered_sid!r}")
                delivered_issuer, _source = meta[frozen_delivered_sid].issuer_key()
            else:
                # A strict-PIT conversion requires issuer authority from replay
                # metadata keyed by the resolved causal ID.  Never reuse the
                # frozen legacy ID as issuer authority.
                if delivered_sid not in meta:
                    raise FrozenTerminalTermsError(
                        f"resolved conversion {frozen_sid} requires replay metadata "
                        f"for delivered causal security {delivered_sid}")
                delivered_issuer, _source = meta[delivered_sid].issuer_key()
            if not delivered_issuer:
                raise FrozenTerminalTermsError(
                    f"delivered security {delivered_sid} has no issuer identity")
            ratio = raw.get("exchange_ratio")
            if not _positive(ratio):
                raise FrozenTerminalTermsError(
                    f"conversion {frozen_sid} has invalid exchange_ratio {ratio!r}")
            cil = raw.get("cash_in_lieu_price_per_delivered_share")
            if cil is not None and not _nonnegative(cil):
                raise FrozenTerminalTermsError(
                    f"conversion {frozen_sid} has invalid cash-in-lieu price {cil!r}")
            kwargs.update(
                delivered_security_id=delivered_sid,
                delivered_ticker=delivered_ticker,
                delivered_issuer_id=str(delivered_issuer),
                exchange_ratio=float(ratio),
                cash_in_lieu_price_per_delivered_share=(
                    None if cil is None else float(cil)),
            )
            if kind_text == "CASH_PLUS_STOCK":
                cash = raw.get("cash_per_share")
                if not _nonnegative(cash):
                    raise FrozenTerminalTermsError(
                        f"mixed terminal {frozen_sid} has invalid cash_per_share {cash!r}")
                kwargs["cash_per_share"] = float(cash)

            witness = raw.get("price_witness")
            if witness is not None:
                if not isinstance(witness, dict):
                    raise FrozenTerminalTermsError(
                        f"conversion {frozen_sid} price_witness must be an object")
                witness_session = _require_text(witness, "session")
                witness_sid = _require_text(witness, "security_id")
                witness_ticker = _require_text(witness, "ticker")
                witness_hash = _require_text(witness, "source_sep_sha256")
                witness_close = witness.get("closeunadj")
                if (witness_session > session or witness_sid != frozen_delivered_sid
                        or witness_ticker != delivered_ticker
                        or not _SHA256.fullmatch(witness_hash)
                        or not _positive(witness_close)):
                    raise FrozenTerminalTermsError(
                        f"conversion {frozen_sid} has invalid price witness")
                if cil is not None and float(witness_close) != float(cil):
                    raise FrozenTerminalTermsError(
                        f"conversion {frozen_sid} cash-in-lieu price disagrees with witness")
        else:
            raise FrozenTerminalTermsError(
                f"research dataset does not admit terminal kind {kind_text!r}")

        terms = TerminalTerms(**kwargs)
        complete, why = terms.completeness(1)
        if not complete:
            raise FrozenTerminalTermsError(
                f"frozen terminal terms for {frozen_sid} are incomplete: {why}")
        by_session.setdefault(session, []).append(terms)

    return ({session: tuple(sorted(items, key=lambda term: term.security_id))
             for session, items in sorted(by_session.items())}, observed)


def merge_terminal_events(
    session: str,
    vendor_events: Sequence[object],
    exact_events: Sequence[object],
) -> tuple[object, ...]:
    """Overlay exact terms for the same session/security economic event."""
    merged: dict[str, object] = {}
    for event in vendor_events:
        if str(event.session) != str(session):
            raise FrozenTerminalTermsError(
                f"vendor terminal event {event.security_id} is off-session")
        sid = str(event.security_id)
        if sid in merged:
            raise FrozenTerminalTermsError(
                f"duplicate vendor terminal event for {sid} on {session}")
        merged[sid] = event
    for event in exact_events:
        if str(event.session) != str(session):
            raise FrozenTerminalTermsError(
                f"exact terminal event {event.security_id} is off-session")
        merged[str(event.security_id)] = event
    return tuple(merged[sid] for sid in sorted(merged))
