"""Broker-free production forward-chain differential for Sentinel.

This is a certification tool, not a runtime decision path.  It drives the
canonical version-3 production state from the beginning of the corrected
lineage's required history, while a single published corpus generation is held
pinned in one read-only, repeatable-read transaction.  It never persists the
state it creates and imports no execution or broker component.

The reference tape has two time bases that must not be collapsed:

* ``allocation[D]`` is the exposure decided at D-1 and effective on D; and
* production ``target_core_exposure`` at D is effective on D+1, so it is
  compared with ``allocation[D+1]``.

The same-row ``parent_allocation`` is decision-basis and is compared with the
production parent severe state at D.  The explicit next-session comparison is
deliberately redundant with the following row's effective-allocation check: it
makes an accidental same-row comparison fail loudly.

Exit codes are 0 for an exact differential pass, 1 for a first divergence, and
2 when the run was refused or could not be completed.  A pass is evidence for
review; this tool changes no certification or execution authority.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import io
import json
import os
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Mapping, Sequence

from sentinel import identity
from sentinel.controller.frozen_rule import load as load_controller
from sentinel.controller.machine import Controller
from sentinel.core.decision import publication_fingerprint, runtime_strategy_identity
from sentinel.core.kernel import advance_session as advance_state
from sentinel.core.loader import load_window
from sentinel.core.production import (
    SessionState,
    load_published_session,
    warm_session_state,
)
from sentinel.feed import calendar, publication
from sentinel.feed.readiness import REQUIRED_SPY_SESSIONS
from sentinel.feed.store import connect, latest_visible_session


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = (
    ROOT / "docs" / "sentinel-reference-implementation"
    / "sentinel_1p1_daily.csv"
)
REFERENCE_CHECKSUMS_PATH = (
    ROOT / "docs" / "sentinel-reference-implementation" / "SHA256SUMS.txt"
)
REFERENCE_ARTIFACT_NAME = "sentinel_1p1_daily.csv"
# The exact entry committed in SHA256SUMS.txt.  Checking both the manifest and
# this frozen value prevents a changed tape plus a changed manifest from being
# mistaken for the reviewed corrected-lineage falsifier.
FROZEN_REFERENCE_SHA256 = (
    "9bf46bfa229888d997072dd4fa3f60f772b208b1e2c55480c8cf65dd7b1c62f7"
)

REPORT_SCHEMA = "sentinel.production-forward-chain/2"
CHAIN_START = "1998-01-02"
REFERENCE_START = "2006-07-31"
REFERENCE_END = "2026-07-31"
CHAIN_SESSION_COUNT = 7_188
REFERENCE_SESSION_COUNT = 5_032
STARTING_CASH = 100_000_000.0

REFERENCE_FIELDS = (
    "date",
    "nav",
    "allocation",
    "parent_allocation",
    "shadow_equity",
    "open_shadow_equity",
    "shadow_dd",
    "damaged",
    "green",
    "r20",
    "r40",
    "stops20",
    "stress_duration",
)
DECIMAL_FIELDS = frozenset(REFERENCE_FIELDS) - {
    "date", "stops20", "stress_duration"
}
INTEGER_FIELDS = frozenset({"stops20", "stress_duration"})

# The scalar live-NAV overlay and intraday shadow mark do not exist in the
# production controller state.  Recomputing either here would create a second
# portfolio implementation, so they are validated as tape data but not used as
# differential fields.
REFERENCE_ONLY_FIELDS = ("nav", "open_shadow_equity")

# Order is diagnostic policy: the first failure is deterministic and starts
# with the two controller outputs before its observation fields.
SAME_SESSION_FIELDS = (
    ("allocation", "effective_allocation",
     "prior_close_decision_to_current_session_effective_allocation"),
    ("parent_allocation", "parent_allocation",
     "current_close_parent_decision"),
    ("shadow_equity", "shadow_equity", "current_close_observation"),
    ("shadow_dd", "shadow_dd", "current_close_observation"),
    ("damaged", "damaged", "current_close_observation"),
    ("green", "green", "current_close_observation"),
    ("r20", "r20", "current_close_observation"),
    ("r40", "r40", "current_close_observation"),
    ("stops20", "stops20", "current_close_observation"),
    ("stress_duration", "stress_duration", "current_close_controller_state"),
)


class ForwardChainRefused(RuntimeError):
    """The differential could not establish its required evidence boundary."""


@dataclass(frozen=True)
class ReferenceRow:
    session: str
    values: Mapping[str, Decimal | int]


@dataclass(frozen=True)
class ReferenceTape:
    rows: tuple[ReferenceRow, ...]
    sha256: str
    path: str
    expected_sha256: str | None = None
    checksum_manifest: str | None = None
    checksum_manifest_sha256: str | None = None

    def identity(self) -> dict:
        return {
            "artifact": self.path,
            "sha256": self.sha256,
            "expected_sha256": self.expected_sha256,
            "checksum_verified": self.sha256 == self.expected_sha256,
            "checksum_manifest": self.checksum_manifest,
            "checksum_manifest_sha256": self.checksum_manifest_sha256,
            "columns": list(REFERENCE_FIELDS),
            "sessions": len(self.rows),
            "first_session": self.rows[0].session if self.rows else None,
            "last_session": self.rows[-1].session if self.rows else None,
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_hash(value) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        default=str,
    ).encode("utf-8")
    return _sha256(payload)


def _decimal(value, *, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ForwardChainRefused(f"{label} is not a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ForwardChainRefused(
            f"{label} is not a finite decimal"
        ) from exc
    if not result.is_finite():
        raise ForwardChainRefused(f"{label} is not a finite decimal")
    return result


def _integer(value: str, *, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ForwardChainRefused(f"{label} is not an integer") from exc
    if str(result) != str(value).strip():
        raise ForwardChainRefused(f"{label} is not an exact integer")
    if result < 0:
        raise ForwardChainRefused(f"{label} must be non-negative")
    return result


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _reference_checksum(
        path: Path = REFERENCE_CHECKSUMS_PATH
        ) -> tuple[str, str, str]:
    """Return the one reviewed tape digest and the manifest's byte identity."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ForwardChainRefused(
            f"reference checksum manifest is unreadable: {path}"
        ) from exc
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ForwardChainRefused(
            "reference checksum manifest is not ASCII"
        ) from exc
    entries: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\\/]+)", line)
        if match is None:
            raise ForwardChainRefused(
                f"reference checksum manifest line {line_number} is malformed"
            )
        if match.group(2) == REFERENCE_ARTIFACT_NAME:
            entries.append(match.group(1))
    if len(entries) != 1:
        raise ForwardChainRefused(
            "reference checksum manifest must contain exactly one entry for "
            f"{REFERENCE_ARTIFACT_NAME}; found {len(entries)}"
        )
    if entries[0] != FROZEN_REFERENCE_SHA256:
        raise ForwardChainRefused(
            "reference checksum manifest entry differs from the frozen "
            f"{REFERENCE_ARTIFACT_NAME} contract"
        )
    return entries[0], _display_path(path), _sha256(raw)


def _parse_reference_bytes(
        raw: bytes, *, path: Path,
        expected_sessions: Sequence[str] | None = None,
        expected_sha256: str | None = None,
        checksum_manifest: str | None = None,
        checksum_manifest_sha256: str | None = None) -> ReferenceTape:
    """Parse already-verified bytes; split out so structural guards are falsified."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ForwardChainRefused("reference tape is not UTF-8") from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != REFERENCE_FIELDS:
        raise ForwardChainRefused(
            "reference tape schema mismatch: expected "
            f"{list(REFERENCE_FIELDS)}, got {list(reader.fieldnames or ())}"
        )

    rows: list[ReferenceRow] = []
    for line_number, raw_row in enumerate(reader, start=2):
        if None in raw_row or set(raw_row) != set(REFERENCE_FIELDS):
            raise ForwardChainRefused(
                f"reference tape row {line_number} has a field-count mismatch"
            )
        session = str(raw_row["date"] or "").strip()
        try:
            # Parsing through date.fromisoformat would add an otherwise unused
            # date object.  XNYS membership below is the stronger validation;
            # this shape guard keeps its error local and comprehensible.
            if (len(session) != 10 or session[4] != "-" or session[7] != "-"
                    or any(not part.isdigit() for part in session.split("-"))):
                raise ValueError
        except ValueError as exc:
            raise ForwardChainRefused(
                f"reference tape row {line_number} has an invalid date"
            ) from exc
        values: dict[str, Decimal | int] = {}
        for field in DECIMAL_FIELDS:
            values[field] = _decimal(
                raw_row[field], label=f"reference row {line_number} {field}"
            )
        for field in INTEGER_FIELDS:
            values[field] = _integer(
                raw_row[field], label=f"reference row {line_number} {field}"
            )
        rows.append(ReferenceRow(session=session, values=values))

    if len(rows) != REFERENCE_SESSION_COUNT:
        raise ForwardChainRefused(
            "reference tape must contain exactly "
            f"{REFERENCE_SESSION_COUNT} sessions; found {len(rows)}"
        )
    if rows[0].session != REFERENCE_START or rows[-1].session != REFERENCE_END:
        raise ForwardChainRefused(
            "reference tape boundary mismatch: expected "
            f"{REFERENCE_START}..{REFERENCE_END}, got "
            f"{rows[0].session}..{rows[-1].session}"
        )
    sessions = [row.session for row in rows]
    if any(left >= right for left, right in zip(sessions, sessions[1:])):
        raise ForwardChainRefused(
            "reference tape sessions are not strictly increasing and unique"
        )
    expected = list(expected_sessions) if expected_sessions is not None else \
        calendar.sessions_in_range(REFERENCE_START, REFERENCE_END)
    if sessions != expected:
        mismatch = next(
            (i for i, pair in enumerate(zip(sessions, expected))
             if pair[0] != pair[1]),
            min(len(sessions), len(expected)),
        )
        actual = sessions[mismatch] if mismatch < len(sessions) else None
        wanted = expected[mismatch] if mismatch < len(expected) else None
        raise ForwardChainRefused(
            "reference tape is not the exact corrected-lineage XNYS session "
            f"axis at index {mismatch}: expected {wanted}, got {actual}"
        )
    return ReferenceTape(
        rows=tuple(rows), sha256=_sha256(raw), path=_display_path(path),
        expected_sha256=expected_sha256,
        checksum_manifest=checksum_manifest,
        checksum_manifest_sha256=checksum_manifest_sha256,
    )


def load_reference_tape(
        path: Path = REFERENCE_PATH, *,
        expected_sessions: Sequence[str] | None = None,
        checksums_path: Path = REFERENCE_CHECKSUMS_PATH) -> ReferenceTape:
    """Load the exact byte-pinned corrected-lineage acceptance tape."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ForwardChainRefused(
            f"reference tape is unreadable: {path}"
        ) from exc
    expected, manifest, manifest_sha256 = _reference_checksum(checksums_path)
    actual = _sha256(raw)
    if actual != expected:
        raise ForwardChainRefused(
            "reference tape checksum mismatch: expected the exact frozen "
            f"{REFERENCE_ARTIFACT_NAME} bytes {expected}, got {actual}"
        )
    return _parse_reference_bytes(
        raw, path=path, expected_sessions=expected_sessions,
        expected_sha256=expected, checksum_manifest=manifest,
        checksum_manifest_sha256=manifest_sha256,
    )


def _require_mapping(value, *, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ForwardChainRefused(f"production state {label} is not a mapping")
    return value


def _actual_for_session(state, *, session: str,
                        effective_allocation) -> dict[str, Decimal | int]:
    decision = _require_mapping(state.last_decision, label="last_decision")
    if decision.get("session") != session:
        raise ForwardChainRefused(
            "production decision session mismatch: expected "
            f"{session}, got {decision.get('session')}"
        )
    evidence = _require_mapping(state.last_evidence, label="last_evidence")
    observation = _require_mapping(
        evidence.get("observation"), label="last_evidence.observation"
    )
    if observation.get("session") != session:
        raise ForwardChainRefused(
            "production observation session mismatch: expected "
            f"{session}, got {observation.get('session')}"
        )
    controller_state = _require_mapping(state.controller, label="controller")
    fast = decision.get("fast_severe_active")
    slow = decision.get("slow_severe_active")
    if not isinstance(fast, bool) or not isinstance(slow, bool):
        raise ForwardChainRefused(
            "production parent severe flags are not booleans"
        )
    stops = observation.get("stops20")
    stress = controller_state.get("base_stress_duration")
    if (isinstance(stops, bool) or not isinstance(stops, int) or stops < 0
            or isinstance(stress, bool) or not isinstance(stress, int)
            or stress < 0):
        raise ForwardChainRefused(
            "production stops20/stress_duration is not a non-negative integer"
        )
    return {
        "effective_allocation": _decimal(
            effective_allocation,
            label=f"production {session} effective allocation",
        ),
        "next_allocation": _decimal(
            decision.get("target_core_exposure"),
            label=f"production {session} target_core_exposure",
        ),
        "parent_allocation": Decimal(0 if fast or slow else 1),
        "shadow_equity": _decimal(
            observation.get("shadow_nav"),
            label=f"production {session} shadow_nav",
        ),
        "shadow_dd": _decimal(
            observation.get("shadow_drawdown"),
            label=f"production {session} shadow_drawdown",
        ),
        "damaged": _decimal(
            observation.get("damaged_breadth"),
            label=f"production {session} damaged_breadth",
        ),
        "green": _decimal(
            observation.get("green_breadth"),
            label=f"production {session} green_breadth",
        ),
        "r20": _decimal(
            observation.get("shadow_r20"),
            label=f"production {session} shadow_r20",
        ),
        "r40": _decimal(
            observation.get("shadow_r40"),
            label=f"production {session} shadow_r40",
        ),
        "stops20": stops,
        "stress_duration": stress,
    }


def _json_value(value):
    return str(value) if isinstance(value, Decimal) else value


def compare_reference_session(
        row: ReferenceRow, actual: Mapping[str, Decimal | int], *,
        next_row: ReferenceRow | None) -> tuple[dict | None, int]:
    """Compare one production close with the reference's explicit time bases."""
    compared = 0
    for reference_field, production_field, alignment in SAME_SESSION_FIELDS:
        compared += 1
        expected = row.values[reference_field]
        observed = actual[production_field]
        if expected != observed:
            return ({
                "production_session": row.session,
                "reference_session": row.session,
                "field": reference_field,
                "production_field": production_field,
                "alignment": alignment,
                "expected": _json_value(expected),
                "actual": _json_value(observed),
            }, compared)
    if next_row is not None:
        compared += 1
        expected = next_row.values["allocation"]
        observed = actual["next_allocation"]
        if expected != observed:
            return ({
                "production_session": row.session,
                "reference_session": next_row.session,
                "field": "allocation",
                "production_field": "target_core_exposure",
                "alignment": "current_close_decision_to_next_session_allocation",
                "expected": _json_value(expected),
                "actual": _json_value(observed),
            }, compared)
    return None, compared


def _known_feed_security_ids(state) -> tuple[str, ...]:
    feed = _require_mapping(state.feed, label="feed")
    series = _require_mapping(feed.get("series"), label="feed.series")
    return tuple(sorted(str(security_id) for security_id in series))


def drive_forward_chain(
        conn, *, chain_sessions: Sequence[str], tape: ReferenceTape,
        controller_config, strategy_identity: Mapping, publication_version: int,
        warm_session_count: int = REQUIRED_SPY_SESSIONS - 1,
        progress: Callable[[int, int, str], None] | None = None) -> dict:
    """Drive only canonical production components and return bounded evidence.

    The first sessions are canonical feature-only warm-up because the published
    SPY loader requires a complete dated 41-session tail.  This is safe for the
    historical chain rather than a portfolio shortcut: the warm interval is
    only 40 sessions, while Wealth Core cannot admit a security before its 127th
    continuous close.  No episode, pending order, controller transition, or
    terminal entitlement can exist during the feature-only interval.
    """
    sessions = list(chain_sessions)
    if (not sessions
            or any(left >= right for left, right in zip(sessions, sessions[1:]))):
        raise ForwardChainRefused(
            "forward-chain sessions are not strictly increasing and unique"
        )
    if (isinstance(warm_session_count, bool)
            or not isinstance(warm_session_count, int)
            or warm_session_count < 1
            or warm_session_count >= len(sessions)):
        raise ForwardChainRefused("forward-chain warm-up count is invalid")
    reference_sessions = [row.session for row in tape.rows]
    try:
        first_reference = sessions.index(reference_sessions[0])
    except (IndexError, ValueError) as exc:
        raise ForwardChainRefused(
            "reference window is absent from the forward-chain session axis"
        ) from exc
    if sessions[first_reference:first_reference + len(reference_sessions)] \
            != reference_sessions:
        raise ForwardChainRefused(
            "reference window is not a contiguous subset of the chain"
        )
    if first_reference < warm_session_count:
        raise ForwardChainRefused(
            "reference comparison begins inside feature-only warm-up"
        )

    controller = Controller(controller_config)
    state = SessionState.fresh(
        starting_cash=STARTING_CASH,
        controller=controller,
        strategy_identity=strategy_identity,
    )
    warm_sessions = sessions[:warm_session_count]
    window = load_window(
        conn, start=warm_sessions[0], end=warm_sessions[-1]
    )
    if list(window.sessions) != warm_sessions:
        raise ForwardChainRefused(
            "feature-only warm-up is not the exact leading XNYS session axis"
        )
    state = warm_session_state(
        state, window, publication_version=publication_version
    )

    reference_by_session = {
        row.session: index for index, row in enumerate(tape.rows)
    }
    advanced = 0
    compared_rows = 0
    field_comparisons = 0
    first_divergence = None
    final_close_decision_boundary = None
    for offset, session in enumerate(sessions[warm_session_count:],
                                     start=warm_session_count):
        prior_decision = state.last_decision
        effective = (
            Decimal(1) if prior_decision is None
            else _decimal(
                _require_mapping(
                    prior_decision, label="prior last_decision"
                ).get("target_core_exposure"),
                label=f"production prior allocation before {session}",
            )
        )
        published = load_published_session(
            conn, session, spy_sessions=REQUIRED_SPY_SESSIONS,
            known_feed_security_ids=_known_feed_security_ids(state),
        )
        if published.session != session:
            raise ForwardChainRefused(
                f"published-session loader returned {published.session} for {session}"
            )
        if int(published.data_version) != int(publication_version):
            raise ForwardChainRefused(
                "loaded publication version differs from the held corpus pin"
            )
        state = advance_state(
            state, published, controller_config=controller_config,
            strategy_identity=strategy_identity,
        )
        if state.last_processed_session != session:
            raise ForwardChainRefused(
                "production transition did not advance to the requested session"
            )
        advanced += 1

        reference_index = reference_by_session.get(session)
        if reference_index is not None:
            actual = _actual_for_session(
                state, session=session, effective_allocation=effective
            )
            next_row = (
                tape.rows[reference_index + 1]
                if reference_index + 1 < len(tape.rows) else None
            )
            if next_row is None:
                # The tape ends at this close.  Record the production output,
                # but do not pretend it has a reference allocation: close-D
                # target becomes observable as allocation only on D+1, whose
                # row is absent from this frozen artifact.
                final_close_decision_boundary = {
                    "production_session": session,
                    "production_field": "target_core_exposure",
                    "actual": _json_value(actual["next_allocation"]),
                    "reference_session": None,
                    "status": "NOT_COMPARABLE_NO_NEXT_REFERENCE_SESSION",
                    "excluded_from_verdict": True,
                }
            divergence, count = compare_reference_session(
                tape.rows[reference_index], actual, next_row=next_row
            )
            compared_rows += 1
            field_comparisons += count
            if divergence is not None:
                first_divergence = divergence
                break
        if progress is not None:
            progress(offset + 1, len(sessions), session)

    return {
        "differential_verdict": (
            "FAIL" if first_divergence is not None
            else "PASS" if compared_rows == len(tape.rows)
            else "REFUSED"
        ),
        "chain_sessions_warmed": len(warm_sessions),
        "chain_sessions_advanced": advanced,
        "reference_sessions_compared": compared_rows,
        "field_comparisons": field_comparisons,
        "first_divergence": first_divergence,
        "final_close_decision_boundary": final_close_decision_boundary,
        "final_state_fingerprint": getattr(state, "state_hash", None),
    }


def _begin_read_only_snapshot(conn) -> dict[str, str]:
    """Make the database boundary explicit before the first corpus read."""
    with conn.cursor() as cur:
        cur.execute(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        )
        cur.execute("SHOW transaction_isolation")
        isolation = str(cur.fetchone()[0]).lower()
        cur.execute("SHOW transaction_read_only")
        read_only = str(cur.fetchone()[0]).lower()
    if isolation != "repeatable read" or read_only not in {"on", "true"}:
        raise ForwardChainRefused(
            "database did not establish a repeatable-read, read-only snapshot"
        )
    return {"isolation": isolation, "read_only": read_only}


def _source_identity(controller_config, strategy: Mapping,
                     reference: ReferenceTape) -> dict:
    environment = identity.environment()
    production_path = Path(inspect.getsourcefile(advance_state) or "")
    runner_path = Path(__file__).resolve()
    return {
        "environment": environment,
        "environment_identity_sha256": _canonical_hash(environment),
        "strategy_identity": dict(strategy),
        "controller_rule_sha256": str(controller_config.digest),
        "production_module": _display_path(production_path),
        "production_module_sha256": _sha256(production_path.read_bytes()),
        "runner": _display_path(runner_path),
        "runner_sha256": _sha256(runner_path.read_bytes()),
        "reference_sha256": reference.sha256,
    }


def _validate_chain_axis(sessions: Sequence[str]) -> None:
    if len(sessions) != CHAIN_SESSION_COUNT:
        raise ForwardChainRefused(
            f"full production chain must contain exactly {CHAIN_SESSION_COUNT} "
            f"XNYS sessions; found {len(sessions)}"
        )
    if sessions[0] != CHAIN_START or sessions[-1] != REFERENCE_END:
        raise ForwardChainRefused(
            "full production chain boundary mismatch: expected "
            f"{CHAIN_START}..{REFERENCE_END}, got "
            f"{sessions[0]}..{sessions[-1]}"
        )


def _validate_corpus_identity(corpus: Mapping, *, publication_version: int) -> None:
    if int(corpus.get("data_version", -1)) != int(publication_version):
        raise ForwardChainRefused(
            "corpus identity version differs from the held publication pin"
        )
    if corpus.get("window") != {"start": CHAIN_START, "end": REFERENCE_END}:
        raise ForwardChainRefused("corpus identity window is not the full chain")
    if (corpus.get("first_session") != CHAIN_START
            or corpus.get("last_session") != REFERENCE_END
            or int(corpus.get("sessions") or 0) != CHAIN_SESSION_COUNT):
        raise ForwardChainRefused(
            "published corpus does not contain the exact full-chain session axis"
        )
    if not corpus.get("corpus_hash"):
        raise ForwardChainRefused("published corpus identity has no corpus hash")


def run_certification(
        conn, *, reference_path: Path = REFERENCE_PATH,
        progress: Callable[[int, int, str], None] | None = None) -> dict:
    """Run the fixed, one-shot differential without changing durable state."""
    transaction = None
    try:
        transaction = _begin_read_only_snapshot(conn)
        tape = load_reference_tape(reference_path)
        chain_sessions = calendar.sessions_in_range(CHAIN_START, REFERENCE_END)
        _validate_chain_axis(chain_sessions)
        controller_config = load_controller()
        strategy = runtime_strategy_identity(controller_config)
        source = _source_identity(controller_config, strategy, tape)

        with publication.pinned(conn, commit=False) as held:
            coherence = publication.assert_coherent(
                conn, exhaustive=True
            ).to_dict()
            held_publication = {
                "publication_fingerprint": publication_fingerprint(held),
                "visible_frontier": latest_visible_session(conn),
            }
            # This is the canonical corpus identity implementation, called
            # inside the already-held pin so identity and transitions cannot
            # name different generations.  The public identity.corpus wrapper
            # would acquire and release a second pin/transaction boundary.
            corpus = identity._corpus_pinned(  # noqa: SLF001
                conn, start=CHAIN_START, end=REFERENCE_END,
                publication_record=held,
            )
            _validate_corpus_identity(corpus, publication_version=held.version)
            result = drive_forward_chain(
                conn, chain_sessions=chain_sessions, tape=tape,
                controller_config=controller_config,
                strategy_identity=strategy,
                publication_version=held.version,
                progress=progress,
            )

        if result["differential_verdict"] == "REFUSED":
            raise ForwardChainRefused(
                "production chain ended without comparing every reference session"
            )
        report = {
            "schema": REPORT_SCHEMA,
            "differential_verdict": result["differential_verdict"],
            "authority_effect": "NONE",
            "runtime_authority_changed": False,
            "manual_review_required": True,
            "reference": tape.identity(),
            "alignment": {
                "reference_allocation": (
                    "effective on row D from the production decision at D-1"
                ),
                "production_target_core_exposure": (
                    "decision at close D compared with reference allocation D+1"
                ),
                "reference_parent_allocation": (
                    "decision at close D compared with production parent state D"
                ),
                "full_pass_allocation_coverage": {
                    "effective_allocations": REFERENCE_SESSION_COUNT,
                    "effective_decision_window": [
                        "2006-07-28", "2026-07-30"
                    ],
                    "close_decisions_compared_to_next_row": (
                        REFERENCE_SESSION_COUNT - 1
                    ),
                    "close_decision_window": [
                        REFERENCE_START, "2026-07-30"
                    ],
                    "uncompared_close_decision": REFERENCE_END,
                },
            },
            "comparison": {
                **result,
                "expected_reference_sessions": REFERENCE_SESSION_COUNT,
                "expected_full_pass_field_comparisons": (
                    REFERENCE_SESSION_COUNT * len(SAME_SESSION_FIELDS)
                    + REFERENCE_SESSION_COUNT - 1
                ),
                "reference_only_fields": list(REFERENCE_ONLY_FIELDS),
            },
            "transaction": transaction,
            "publication_coherence": coherence,
            "held_publication": held_publication,
            "corpus_identity": corpus,
            "source_identity": source,
        }
        return report
    finally:
        # No code path commits.  Rollback also proves a future accidental write
        # cannot hitch a ride out of this process even if PostgreSQL's READ ONLY
        # guard were weakened elsewhere.
        conn.rollback()


def _write_report(report: Mapping, output: Path | None) -> None:
    payload = json.dumps(
        report, sort_keys=True, indent=2, allow_nan=False, default=str
    ) + "\n"
    if output is None:
        sys.stdout.write(payload)
        return
    output = Path(output)
    if not output.parent.exists():
        raise ForwardChainRefused(
            f"output artifact directory does not exist: {output.parent}"
        )
    temporary = output.with_name(f".{output.name}.tmp.{os.getpid()}")
    published = False
    directory_fd: int | None = None
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic no-clobber publication.  A preflight ``exists`` followed by
        # ``replace`` lets a concurrently-created evidence file be overwritten
        # between those calls.  The hard link either gives the completed inode
        # its final name or fails with FileExistsError; there is no overwrite
        # window and the temporary name remains available for cleanup.
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise ForwardChainRefused(
                f"output artifact already exists; refusing overwrite: {output}"
            ) from exc
        published = True
        # The final name is evidence only after its directory entry is durable.
        # The certification image is Linux; O_DIRECTORY prevents a surprising
        # non-directory path from being synchronized as if publication were
        # complete.
        directory_fd = os.open(
            output.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        os.fsync(directory_fd)
        os.close(directory_fd)
        directory_fd = None
        # Keep cleanup operations inside the guarded region: if removing the
        # temporary name reports failure, the command must not leave the final
        # PASS name behind while also exiting unsuccessfully.
        temporary.unlink()
    except BaseException:
        if published:
            # A hard-linked report is not valid evidence until the parent
            # directory fsync succeeds.  Remove the final name on every
            # post-link failure so a complete-looking PASS cannot survive a
            # command that reported failure.  Synchronize the removal when the
            # filesystem still permits it; failure here must not hide the
            # original publication error.
            try:
                output.unlink()
            except FileNotFoundError:
                pass
            cleanup_fd = directory_fd
            opened_for_cleanup = False
            if cleanup_fd is None:
                try:
                    cleanup_fd = os.open(
                        output.parent,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                    )
                    opened_for_cleanup = True
                except OSError:
                    cleanup_fd = None
            if cleanup_fd is not None:
                try:
                    os.fsync(cleanup_fd)
                except OSError:
                    pass
                finally:
                    if opened_for_cleanup:
                        try:
                            os.close(cleanup_fd)
                        except OSError:
                            pass
        raise
    finally:
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass
        try:
            temporary.unlink()
        except OSError:
            pass


def _progress(processed: int, total: int, session: str) -> None:
    if processed % 252 == 0 or processed == total:
        print(
            f"forward-chain: {processed}/{total} sessions through {session}",
            file=sys.stderr, flush=True,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the broker-free canonical Sentinel production forward-chain "
            "differential against the fixed corrected-lineage tape."
        )
    )
    parser.add_argument(
        "--output", type=Path,
        help="write one new JSON evidence artifact; stdout when omitted",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="suppress 252-session progress"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database_url = os.environ.get("SENTINEL_DATABASE_URL")
    if not database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 2
    conn = None
    try:
        conn = connect(database_url)
        report = run_certification(
            conn, progress=None if args.quiet else _progress
        )
        _write_report(report, args.output)
        return 0 if report["differential_verdict"] == "PASS" else 1
    except ForwardChainRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - refusal boundary for one-shot CLI
        print(
            f"REFUSED: forward chain failed ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
