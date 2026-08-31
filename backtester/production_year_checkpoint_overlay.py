#!/usr/bin/env python3
"""Strict annual checkpoint support for the production-only PIT replay.

Format 3 is an authenticated restart image, not a recorded decision tape. It
contains only state produced by the same chronological chain and refuses to
resume unless source, canonical prefix, economic state, continuation state, and
the cumulative output prefix all reproduce exactly.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import textwrap
from typing import Callable, Mapping, Sequence


SCHEMA = "backtester.production-year-checkpoint/3"
FORMAT_GENERATION = 3
GENERATION = FORMAT_GENERATION
FULL_DATASET_END = "2026-07-31"
GENESIS_YEAR = 2006

DAILY_COLUMNS = (
    "date",
    "A_nav",
    "B_nav",
    "SPY_level",
    "wealth_core_equity",
    "A_allocation",
    "B_allocation",
    "A_native",
    "B_native",
    "A_damaged",
    "B_damaged",
    "green",
    "D_eligible_universe",
    "D_ranking_count",
    "D_ranking_sha256",
    "D_selected_positions_sha256",
    "D_selected_positions",
    "D_intents",
    "D_ldrc_state",
)

ENVELOPE_FIELDS = frozenset(
    {"schema", "format_generation", "payload_sha256", "payload"}
)
PAYLOAD_FIELDS = frozenset(
    {
        "identities",
        "canonical",
        "chain",
        "states",
        "accounts",
        "raw_bookkeeping",
        "module_state",
        "daily",
    }
)
IDENTITY_FIELDS = frozenset(
    {
        "experiment",
        "backtester_sha",
        "production_main_sha",
        "production_overlay_sha256",
        "checkpoint_module_sha256",
    }
)
CANONICAL_FIELDS = frozenset(
    {"dataset_hash", "manifest_sha256", "full_dataset_end"}
)
CHAIN_FIELDS = frozenset(
    {
        "chain_start",
        "measurement_start",
        "segment_year",
        "end_session",
        "session_hash",
        "expected_pointer",
        "canonical_prefix_sha256",
        "next_session",
        "next_session_hash",
        "previous_checkpoint_sha256",
    }
)
ROLE_TO_INTERNAL = {"scaffold": "A", "production": "B"}
CHECKPOINT_CONTRACT_MARKERS = (
    "production_core_by_session",
    "canonical_prefix_sha256",
    "daily_prefix_sha256",
    "previous_checkpoint_sha256",
)


def _json_default(value):
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(
        f"checkpoint value is not JSON serializable: {type(value).__name__}"
    )


def canonical_json(value) -> bytes:
    """Return the one canonical byte representation used by all inner hashes."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def hash_value(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect_fields(value, expected: frozenset[str], label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"production checkpoint {label} must be an object")
    actual = set(value)
    if actual != set(expected):
        raise RuntimeError(
            f"production checkpoint {label} fields differ: "
            f"{sorted(actual ^ set(expected))}"
        )
    if any(type(key) is not str for key in value):
        raise RuntimeError(f"production checkpoint {label} has a non-string key")
    return value


def _is_int(value) -> bool:
    return type(value) is int


def _finite(value, label: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise RuntimeError(f"production checkpoint {label} is not numeric")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise RuntimeError(f"production checkpoint {label} is not {qualifier}")
    return number


def _unit_interval(value, label: str) -> float:
    number = _finite(value, label)
    if not 0.0 <= number <= 1.0:
        raise RuntimeError(f"production checkpoint {label} is outside [0,1]")
    return number


def _nonnegative_int(value, label: str) -> int:
    if not _is_int(value) or value < 0:
        raise RuntimeError(
            f"production checkpoint {label} is not a non-negative integer"
        )
    return value


def _hex_digest(value, label: str, *, length: int = 64) -> str:
    if (
        type(value) is not str
        or len(value) != length
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise RuntimeError(f"production checkpoint {label} is not a {length}-hex digest")
    return value


def _date_text(value, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 10
        or value[4:5] != "-"
        or value[7:8] != "-"
        or not (value[:4] + value[5:7] + value[8:]).isdigit()
    ):
        raise RuntimeError(f"production checkpoint {label} is not an ISO date")
    return value


def _strict_json_object(raw: str):
    def reject_constant(value):
        raise RuntimeError(f"production checkpoint contains non-finite JSON {value}")

    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError(
                    f"production checkpoint contains duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            parse_constant=reject_constant,
            object_pairs_hook=no_duplicate_keys,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"production checkpoint JSON is invalid: {exc}") from exc


def current_identities(
    *, experiment: str, production_main_sha: str, checkpoint_module_sha256: str
) -> dict:
    backtester_sha = os.environ.get("BACKTESTER_BRANCH_SHA", "").strip()
    overlay_sha = os.environ.get("PRODUCTION_OVERLAY_SHA256", "").strip()
    if not experiment:
        raise RuntimeError("production checkpoint experiment identity is empty")
    _hex_digest(backtester_sha, "backtester source SHA", length=40)
    _hex_digest(production_main_sha, "production main SHA", length=40)
    _hex_digest(overlay_sha, "applied production overlay SHA256")
    _hex_digest(checkpoint_module_sha256, "checkpoint module SHA256")
    return {
        "experiment": str(experiment),
        "backtester_sha": backtester_sha,
        "production_main_sha": str(production_main_sha),
        "production_overlay_sha256": overlay_sha,
        "checkpoint_module_sha256": str(checkpoint_module_sha256),
    }


def encode_daily_rows(rows: Sequence[Mapping]) -> list[list]:
    """Encode mappings as arrays so JSON key sorting cannot reorder CSV columns."""
    encoded: list[list] = []
    expected = set(DAILY_COLUMNS)
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != expected:
            actual = set(row) if isinstance(row, Mapping) else set()
            raise RuntimeError(
                f"production checkpoint daily row {index} fields differ: "
                f"{sorted(actual ^ expected)}"
            )
        encoded.append([row[column] for column in DAILY_COLUMNS])
    return json.loads(canonical_json(encoded))


def decode_daily_rows(columns: Sequence[str], rows: Sequence[Sequence]) -> list[dict]:
    if type(columns) is not list or columns != list(DAILY_COLUMNS):
        raise RuntimeError("production checkpoint daily column order changed")
    if type(rows) is not list:
        raise RuntimeError("production checkpoint daily rows must be an array")
    decoded = []
    for index, row in enumerate(rows):
        if type(row) is not list or len(row) != len(DAILY_COLUMNS):
            raise RuntimeError(
                f"production checkpoint daily row {index} has wrong width"
            )
        decoded.append(dict(zip(DAILY_COLUMNS, row)))
    return decoded


def daily_prefix_hash(columns: Sequence[str], rows: Sequence[Sequence]) -> str:
    return hash_value({"columns": list(columns), "rows": list(rows)})


def _reject_json_constant(token: str):
    raise ValueError(f"non-finite JSON {token}")


def _validate_json_string(value, label: str, expected_type, *, sorted_keys: bool):
    if type(value) is not str:
        raise RuntimeError(f"production checkpoint {label} is not a JSON string")
    try:
        decoded = json.loads(value, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"production checkpoint {label} JSON is invalid") from exc
    if type(decoded) is not expected_type:
        raise RuntimeError(f"production checkpoint {label} JSON has wrong type")
    canonical = json.dumps(
        decoded, sort_keys=sorted_keys, separators=(",", ":"), allow_nan=False
    )
    if value != canonical:
        raise RuntimeError(f"production checkpoint {label} JSON is not canonical")
    return decoded


def _validate_daily(daily: Mapping, *, expected_dates: Sequence[str]) -> list[dict]:
    _expect_fields(daily, frozenset({"columns", "rows", "prefix_sha256"}), "daily")
    columns = daily["columns"]
    rows = daily["rows"]
    decoded = decode_daily_rows(columns, rows)
    _hex_digest(daily["prefix_sha256"], "daily prefix SHA256")
    if daily["prefix_sha256"] != daily_prefix_hash(columns, rows):
        raise RuntimeError("production checkpoint daily prefix hash mismatch")
    if len(decoded) != len(expected_dates):
        raise RuntimeError("production checkpoint daily prefix length differs from pointer")

    for index, (row, expected_date) in enumerate(zip(decoded, expected_dates)):
        prefix = f"daily row {index}"
        if _date_text(row["date"], f"{prefix} date") != expected_date:
            raise RuntimeError(
                f"production checkpoint daily dates differ at {index}: "
                f"{row['date']!r} != {expected_date!r}"
            )
        for column in ("A_nav", "B_nav", "SPY_level", "wealth_core_equity"):
            _finite(row[column], f"{prefix} {column}", positive=True)
        for column in ("A_allocation", "B_allocation"):
            _unit_interval(row[column], f"{prefix} {column}")
        for column in ("A_native", "B_native"):
            if row[column] is not None:
                _unit_interval(row[column], f"{prefix} {column}")
        for column in ("A_damaged", "B_damaged", "green"):
            value = row[column]
            if value is not None and type(value) not in (bool, int, float):
                raise RuntimeError(f"production checkpoint {prefix} {column} has wrong type")
            if type(value) in (int, float):
                _finite(value, f"{prefix} {column}")
        eligible = _nonnegative_int(
            row["D_eligible_universe"], f"{prefix} eligible universe"
        )
        ranking = _nonnegative_int(row["D_ranking_count"], f"{prefix} ranking count")
        if ranking > eligible:
            raise RuntimeError(f"production checkpoint {prefix} ranking exceeds universe")
        _hex_digest(row["D_ranking_sha256"], f"{prefix} ranking SHA256")
        _hex_digest(
            row["D_selected_positions_sha256"],
            f"{prefix} selected positions SHA256",
        )
        positions = _validate_json_string(
            row["D_selected_positions"],
            f"{prefix} selected positions",
            list,
            sorted_keys=False,
        )
        if any(type(item) is not str for item in positions):
            raise RuntimeError(f"production checkpoint {prefix} positions are mistyped")
        selected_digest = hashlib.sha256(row["D_selected_positions"].encode()).hexdigest()
        if row["D_selected_positions_sha256"] != selected_digest:
            raise RuntimeError(
                f"production checkpoint {prefix} selected-position hash mismatch"
            )
        _validate_json_string(
            row["D_intents"], f"{prefix} intents", list, sorted_keys=True
        )
        ldrc = _validate_json_string(
            row["D_ldrc_state"], f"{prefix} LD-RC state", dict, sorted_keys=True
        )
        _expect_fields(
            ldrc,
            frozenset({"episode", "latched", "prev_desired", "prev_native", "streak"}),
            f"{prefix} LD-RC state",
        )
        if type(ldrc["episode"]) is not bool or type(ldrc["latched"]) is not bool:
            raise RuntimeError(f"production checkpoint {prefix} LD-RC flags are mistyped")
        _unit_interval(ldrc["prev_desired"], f"{prefix} previous desired")
        _unit_interval(ldrc["prev_native"], f"{prefix} previous native")
        _nonnegative_int(ldrc["streak"], f"{prefix} recovery streak")
    return decoded


def _canonical_prefix_hash(
    sessions: Sequence[str], pointer: int, session_hash: Callable[[str], str]
) -> str:
    rows = []
    for value in sessions[:pointer]:
        digest = session_hash(str(value))
        _hex_digest(digest, f"canonical session {value} SHA256")
        rows.append([str(value), digest])
    return hash_value(rows)


def validate_segment_axis(
    sessions: Sequence[str], *, chain_start: str, segment_end: str
) -> dict:
    values = [str(value) for value in sessions]
    if not values or values[0] != str(chain_start) or values[-1] != FULL_DATASET_END:
        raise RuntimeError(
            "canonical full session axis does not match production chain boundaries"
        )
    if any(right <= left for left, right in zip(values, values[1:])):
        raise RuntimeError("canonical full session axis is not strictly ordered")
    try:
        end_index = values.index(str(segment_end))
    except ValueError as exc:
        raise RuntimeError(
            f"production segment end is outside canonical axis: {segment_end}"
        ) from exc
    year = int(str(segment_end)[:4])
    if year < GENESIS_YEAR or year > int(FULL_DATASET_END[:4]):
        raise RuntimeError(f"production checkpoint segment year is invalid: {year}")
    next_session = values[end_index + 1] if end_index + 1 < len(values) else None
    if str(segment_end) == FULL_DATASET_END:
        if next_session is not None:
            raise RuntimeError("final production segment unexpectedly has a next session")
    elif next_session is None or next_session[:4] == str(year):
        raise RuntimeError(
            f"production segment {year} does not end on its final canonical session"
        )
    return {
        "segment_year": year,
        "pointer": end_index + 1,
        "next_session": next_session,
    }


def _validate_identities(value: Mapping, expected: Mapping) -> None:
    _expect_fields(value, IDENTITY_FIELDS, "identities")
    if dict(value) != dict(expected):
        raise RuntimeError("production checkpoint source identities changed")
    if type(value["experiment"]) is not str or not value["experiment"]:
        raise RuntimeError("production checkpoint experiment identity is empty")
    _hex_digest(value["backtester_sha"], "backtester source SHA", length=40)
    _hex_digest(value["production_main_sha"], "production main SHA", length=40)
    _hex_digest(value["production_overlay_sha256"], "production overlay SHA256")
    _hex_digest(value["checkpoint_module_sha256"], "checkpoint module SHA256")


def _validate_account(raw: Mapping, role: str, expected_nav: float) -> None:
    _expect_fields(
        raw,
        frozenset(
            {
                "role",
                "nav",
                "effective",
                "pending",
                "initialized",
                "transition_cost",
                "transitions",
            }
        ),
        f"{role} account",
    )
    if raw["role"] != role:
        raise RuntimeError(f"production checkpoint {role} account role changed")
    nav = _finite(raw["nav"], f"{role} account NAV", positive=True)
    if nav != expected_nav:
        raise RuntimeError(f"production checkpoint {role} account NAV differs from daily")
    _unit_interval(raw["effective"], f"{role} effective exposure")
    _unit_interval(raw["pending"], f"{role} pending exposure")
    if type(raw["initialized"]) is not bool or not raw["initialized"]:
        raise RuntimeError(f"production checkpoint {role} account is not initialized")
    cost = _finite(raw["transition_cost"], f"{role} transition cost")
    if cost < 0:
        raise RuntimeError(f"production checkpoint {role} transition cost is negative")
    _nonnegative_int(raw["transitions"], f"{role} transition count")


def _validate_raw_bookkeeping(raw: Mapping, *, pointer: int, last_row: Mapping) -> None:
    _expect_fields(
        raw,
        frozenset(
            {
                "prior_split_factor",
                "seen_count",
                "prior_signal_close",
                "latest_ticker_by_sid",
                "scaffold_prior_core_close",
            }
        ),
        "raw bookkeeping",
    )
    maps = {}
    for name in (
        "prior_split_factor",
        "seen_count",
        "prior_signal_close",
        "latest_ticker_by_sid",
    ):
        value = raw[name]
        if type(value) is not dict or any(type(key) is not str or not key for key in value):
            raise RuntimeError(f"production checkpoint {name} has invalid domain")
        maps[name] = value
    domain = set(maps["prior_split_factor"])
    if (
        not domain
        or set(maps["seen_count"]) != domain
        or set(maps["latest_ticker_by_sid"]) != domain
    ):
        raise RuntimeError("production checkpoint raw bookkeeping domains differ")
    if not set(maps["prior_signal_close"]).issubset(domain):
        raise RuntimeError("production checkpoint signal-close domain is invalid")
    for sid, value in maps["prior_split_factor"].items():
        _finite(value, f"prior split factor {sid}", positive=True)
    for sid, value in maps["seen_count"].items():
        if not _is_int(value) or value <= 0:
            raise RuntimeError(f"production checkpoint seen count {sid} is invalid")
    for sid, value in maps["latest_ticker_by_sid"].items():
        if type(value) is not str or not value:
            raise RuntimeError(f"production checkpoint latest ticker {sid} is invalid")
    for sid, value in maps["prior_signal_close"].items():
        if type(value) is not list or len(value) != 2:
            raise RuntimeError(f"production checkpoint prior signal close {sid} is invalid")
        if not _is_int(value[0]) or not 0 <= value[0] < pointer:
            raise RuntimeError(f"production checkpoint prior signal index {sid} is invalid")
        _finite(value[1], f"prior signal close {sid}", positive=True)
    prior = _finite(
        raw["scaffold_prior_core_close"],
        "scaffold prior Wealth Core close",
        positive=True,
    )
    if prior != float(last_row["wealth_core_equity"]):
        raise RuntimeError(
            "production checkpoint scaffold prior Wealth Core close differs from daily"
        )


def _validate_module_state(
    raw: Mapping,
    *,
    expected_dates: Sequence[str],
    strict_keys: Sequence[str],
) -> None:
    _expect_fields(raw, frozenset({"fullstack", "strict", "progress"}), "module state")
    fullstack = _expect_fields(
        raw["fullstack"],
        frozenset(
            {
                "production_prior_core_close",
                "production_core_by_session",
                "pit_metadata_observations",
                "pit_sec_cik_observations",
            }
        ),
        "full-stack module state",
    )
    history = fullstack["production_core_by_session"]
    if type(history) is not list or len(history) != len(expected_dates):
        raise RuntimeError("production checkpoint Production core history length changed")
    last_close = None
    for index, (row, expected_date) in enumerate(zip(history, expected_dates)):
        if type(row) is not list or len(row) != 3 or row[0] != expected_date:
            raise RuntimeError(
                f"production checkpoint Production core history differs at {index}"
            )
        if row[1] is not None:
            _finite(row[1], f"Production core open {expected_date}", positive=True)
        last_close = _finite(
            row[2], f"Production core close {expected_date}", positive=True
        )
    prior = _finite(
        fullstack["production_prior_core_close"],
        "Production prior Wealth Core close",
        positive=True,
    )
    if prior != last_close:
        raise RuntimeError(
            "production checkpoint Production prior Wealth Core close differs from history"
        )
    total = _nonnegative_int(
        fullstack["pit_metadata_observations"], "PIT metadata observations"
    )
    sec = _nonnegative_int(
        fullstack["pit_sec_cik_observations"], "PIT SEC CIK observations"
    )
    if sec > total:
        raise RuntimeError("production checkpoint PIT SEC observations exceed total")

    strict = _expect_fields(
        raw["strict"], frozenset({"anchor_issuer_stats"}), "strict module state"
    )
    stats = strict["anchor_issuer_stats"]
    if type(stats) is not dict or set(stats) != set(strict_keys):
        raise RuntimeError("production checkpoint anchor authority keys changed")
    for key, value in stats.items():
        _nonnegative_int(value, f"anchor authority counter {key}")
    if set(stats) == {"anchors", "sec_cik", "unknown_singleton"}:
        if stats["anchors"] != stats["sec_cik"] + stats["unknown_singleton"]:
            raise RuntimeError("production checkpoint anchor authority counters disagree")

    progress = _expect_fields(
        raw["progress"], frozenset({"progress_sessions"}), "progress module state"
    )
    count = _nonnegative_int(progress["progress_sessions"], "progress session count")
    if count != len(expected_dates):
        raise RuntimeError("production checkpoint progress count differs from pointer")


def validate_payload(
    payload: Mapping,
    *,
    expected_identities: Mapping,
    dataset_hash: str,
    manifest_sha256: str,
    chain_start: str,
    measurement_start: str,
    current_end_session: str | None,
    sessions: Sequence[str],
    session_hash: Callable[[str], str],
    strict_keys: Sequence[str],
    allow_unlinked_equivalence: bool = False,
) -> list[dict]:
    """Validate one payload and, when supplied, its next-segment relationship."""
    _expect_fields(payload, PAYLOAD_FIELDS, "payload")
    _validate_identities(payload["identities"], expected_identities)

    canonical = _expect_fields(payload["canonical"], CANONICAL_FIELDS, "canonical identity")
    if canonical["dataset_hash"] != dataset_hash:
        raise RuntimeError("production checkpoint canonical dataset hash changed")
    _hex_digest(canonical["dataset_hash"], "canonical dataset hash")
    if canonical["manifest_sha256"] != manifest_sha256:
        raise RuntimeError("production checkpoint canonical manifest hash changed")
    _hex_digest(canonical["manifest_sha256"], "canonical manifest SHA256")
    if canonical["full_dataset_end"] != FULL_DATASET_END:
        raise RuntimeError("production checkpoint full dataset end changed")

    chain = _expect_fields(payload["chain"], CHAIN_FIELDS, "chain")
    if chain["chain_start"] != chain_start or chain["measurement_start"] != measurement_start:
        raise RuntimeError("production checkpoint chain/measurement start changed")
    _date_text(chain["chain_start"], "chain start")
    _date_text(chain["measurement_start"], "measurement start")
    checkpoint_year = chain["segment_year"]
    if not _is_int(checkpoint_year):
        raise RuntimeError("production checkpoint segment year is mistyped")
    if (
        type(chain["end_session"]) is not str
        or chain["end_session"][:4] != str(checkpoint_year)
    ):
        raise RuntimeError("production checkpoint end session/year disagree")
    _date_text(chain["end_session"], "checkpoint end session")
    checkpoint_axis = validate_segment_axis(
        sessions, chain_start=chain_start, segment_end=chain["end_session"]
    )
    if checkpoint_axis["segment_year"] != checkpoint_year:
        raise RuntimeError("production checkpoint segment year changed")
    pointer = chain["expected_pointer"]
    if (
        not _is_int(pointer)
        or pointer <= 0
        or pointer > len(sessions)
        or pointer != checkpoint_axis["pointer"]
    ):
        raise RuntimeError("production checkpoint session pointer is invalid")
    if sessions[pointer - 1] != chain["end_session"]:
        raise RuntimeError("production checkpoint session pointer witnesses disagree")
    expected_next = checkpoint_axis["next_session"]
    if chain["next_session"] != expected_next:
        raise RuntimeError("production checkpoint next-session witness changed")
    if expected_next is not None:
        _date_text(chain["next_session"], "checkpoint next session")
        if chain["next_session"][:4] != str(checkpoint_year + 1):
            raise RuntimeError("production checkpoint next-session year is not contiguous")
    expected_end_hash = session_hash(chain["end_session"])
    expected_next_hash = None if expected_next is None else session_hash(expected_next)
    if chain["session_hash"] != expected_end_hash:
        raise RuntimeError("production checkpoint final canonical session hash changed")
    if chain["next_session_hash"] != expected_next_hash:
        raise RuntimeError("production checkpoint next canonical session hash changed")
    _hex_digest(chain["session_hash"], "checkpoint session SHA256")
    if expected_next_hash is not None:
        _hex_digest(chain["next_session_hash"], "checkpoint next-session SHA256")
    expected_prefix = _canonical_prefix_hash(sessions, pointer, session_hash)
    if chain["canonical_prefix_sha256"] != expected_prefix:
        raise RuntimeError("production checkpoint canonical prefix hash changed")
    _hex_digest(chain["canonical_prefix_sha256"], "canonical prefix SHA256")
    predecessor = chain["previous_checkpoint_sha256"]
    if checkpoint_year == GENESIS_YEAR:
        if predecessor is not None:
            raise RuntimeError("production genesis checkpoint has a predecessor digest")
    else:
        if predecessor is None:
            if not allow_unlinked_equivalence:
                raise RuntimeError(
                    "non-genesis production checkpoint lacks a predecessor digest"
                )
        else:
            _hex_digest(predecessor, "previous checkpoint SHA256")

    if current_end_session is not None:
        current_axis = validate_segment_axis(
            sessions, chain_start=chain_start, segment_end=current_end_session
        )
        if checkpoint_year != current_axis["segment_year"] - 1:
            raise RuntimeError("production checkpoint predecessor year is not contiguous")
        if expected_next is None or expected_next[:4] != str(current_axis["segment_year"]):
            raise RuntimeError("production checkpoint does not witness the next segment")

    expected_dates = [str(value) for value in sessions[:pointer]]
    daily_rows = _validate_daily(payload["daily"], expected_dates=expected_dates)
    states = _expect_fields(payload["states"], frozenset(ROLE_TO_INTERNAL), "states")
    for role in ROLE_TO_INTERNAL:
        entry = _expect_fields(
            states[role], frozenset({"state", "state_hash"}), f"{role} state"
        )
        if type(entry["state"]) is not dict:
            raise RuntimeError(f"production checkpoint {role} state is not an object")
        _hex_digest(entry["state_hash"], f"{role} state hash")
        canonical_json(entry["state"])

    accounts = _expect_fields(payload["accounts"], frozenset(ROLE_TO_INTERNAL), "accounts")
    _validate_account(accounts["scaffold"], "scaffold", float(daily_rows[-1]["A_nav"]))
    _validate_account(accounts["production"], "production", float(daily_rows[-1]["B_nav"]))
    _validate_raw_bookkeeping(
        payload["raw_bookkeeping"], pointer=pointer, last_row=daily_rows[-1]
    )
    _validate_module_state(
        payload["module_state"], expected_dates=expected_dates, strict_keys=strict_keys
    )
    return daily_rows


def _sidecar_path(path: Path) -> Path:
    return Path(str(path) + ".sha256")


def load_checkpoint(path: Path) -> dict:
    """Load an envelope only after mandatory complete-file and payload checks."""
    path = Path(path).resolve()
    if not path.is_file():
        raise RuntimeError(f"production checkpoint is missing: {path}")
    sidecar = _sidecar_path(path)
    if not sidecar.is_file():
        raise RuntimeError(f"production checkpoint hash sidecar is missing: {sidecar}")
    parts = sidecar.read_text(encoding="utf-8").strip().split()
    if len(parts) != 2 or parts[1].lstrip("*") != path.name:
        raise RuntimeError("production checkpoint hash sidecar is malformed")
    _hex_digest(parts[0], "checkpoint file SHA256")
    observed_file = sha256_file(path)
    if observed_file != parts[0]:
        raise RuntimeError("production checkpoint complete-file SHA256 mismatch")

    envelope = _strict_json_object(path.read_text(encoding="utf-8"))
    _expect_fields(envelope, ENVELOPE_FIELDS, "envelope")
    if envelope["schema"] != SCHEMA:
        raise RuntimeError(f"unsupported production checkpoint schema: {envelope['schema']!r}")
    if (
        not _is_int(envelope["format_generation"])
        or envelope["format_generation"] != FORMAT_GENERATION
    ):
        raise RuntimeError("production checkpoint format generation changed")
    if type(envelope["payload"]) is not dict:
        raise RuntimeError("production checkpoint payload is missing")
    _hex_digest(envelope["payload_sha256"], "payload SHA256")
    observed_payload = hash_value(envelope["payload"])
    if envelope["payload_sha256"] != observed_payload:
        raise RuntimeError("production checkpoint payload SHA256 mismatch")
    return envelope["payload"]


def write_checkpoint(path: Path, payload: Mapping) -> str:
    """Atomically write the authenticated envelope and mandatory sidecar."""
    path = Path(path).resolve()
    envelope = {
        "schema": SCHEMA,
        "format_generation": FORMAT_GENERATION,
        "payload_sha256": hash_value(payload),
        "payload": payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            envelope,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    digest = sha256_file(path)
    sidecar = _sidecar_path(path)
    sidecar_tmp = sidecar.with_name(sidecar.name + ".tmp")
    sidecar_tmp.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    os.replace(sidecar_tmp, sidecar)
    return digest


def _account_payload(account, role: str) -> dict:
    if str(account.name) != ROLE_TO_INTERNAL[role]:
        raise RuntimeError(f"production checkpoint account mapping changed for {role}")
    return {
        "role": role,
        "nav": float(account.nav),
        "effective": float(account.effective),
        "pending": float(account.pending),
        "initialized": bool(account.initialized),
        "transition_cost": float(account.transition_cost),
        "transitions": int(account.transitions),
    }


def _restore_account(account_class, raw: Mapping, role: str):
    account = account_class(ROLE_TO_INTERNAL[role])
    account.nav = float(raw["nav"])
    account.effective = float(raw["effective"])
    account.pending = float(raw["pending"])
    account.initialized = raw["initialized"]
    account.transition_cost = float(raw["transition_cost"])
    account.transitions = raw["transitions"]
    return account


def build_payload(
    *,
    identities: Mapping,
    canonical_dataset,
    canonical_manifest_sha256: str,
    chain_start: str,
    measurement_start: str,
    end_session: str,
    expected_pointer: int,
    previous_checkpoint_sha256: str | None,
    state_a,
    state_b,
    accounts: Mapping,
    prior_split_factor: Mapping,
    seen_count: Mapping,
    prior_signal_close: Mapping,
    latest_ticker_by_sid: Mapping,
    scaffold_prior_core_close,
    daily_rows: Sequence[Mapping],
    fullstack_module,
    strict_module,
    progress_module,
    allow_unlinked_equivalence: bool = False,
) -> dict:
    sessions = [str(value) for value in canonical_dataset.sessions]
    axis = validate_segment_axis(
        sessions, chain_start=chain_start, segment_end=end_session
    )
    if expected_pointer != axis["pointer"]:
        raise RuntimeError("production checkpoint output pointer differs from canonical axis")
    if axis["segment_year"] == GENESIS_YEAR:
        if previous_checkpoint_sha256 is not None:
            raise RuntimeError("production genesis checkpoint cannot name a predecessor")
    else:
        if previous_checkpoint_sha256 is None:
            if not allow_unlinked_equivalence:
                raise RuntimeError(
                    "non-genesis production checkpoint requires a predecessor"
                )
        else:
            _hex_digest(previous_checkpoint_sha256, "previous checkpoint SHA256")
    if set(accounts) != {"A", "B"}:
        raise RuntimeError("production checkpoint requires exactly two internal accounts")
    for state, label in ((state_a, "scaffold"), (state_b, "production")):
        if str(state.last_processed_session) != end_session:
            raise RuntimeError(f"production checkpoint {label} state boundary changed")
        _hex_digest(str(state.state_hash), f"{label} state hash")

    encoded_daily = encode_daily_rows(daily_rows)
    fullstack_history = getattr(fullstack_module, "_pit_core_by_session", None)
    if not isinstance(fullstack_history, dict):
        raise RuntimeError("Production core history is unavailable at checkpoint")
    history_rows = []
    for session in sessions[:expected_pointer]:
        if session not in fullstack_history:
            raise RuntimeError(f"Production core history lacks {session}")
        value = fullstack_history[session]
        if type(value) not in (tuple, list) or len(value) != 2:
            raise RuntimeError(f"Production core history {session} has invalid value")
        history_rows.append(
            [session, None if value[0] is None else float(value[0]), float(value[1])]
        )
    if set(fullstack_history) != set(sessions[:expected_pointer]):
        raise RuntimeError("Production core history domain differs from canonical prefix")

    state_a_dict = json.loads(canonical_json(state_a.to_dict()))
    state_b_dict = json.loads(canonical_json(state_b.to_dict()))
    strict_stats = getattr(strict_module, "_anchor_issuer_stats", None)
    if not isinstance(strict_stats, dict):
        raise RuntimeError("strict issuer authority counters are unavailable")
    payload = {
        "identities": dict(identities),
        "canonical": {
            "dataset_hash": str(canonical_dataset.dataset_hash),
            "manifest_sha256": str(canonical_manifest_sha256),
            "full_dataset_end": FULL_DATASET_END,
        },
        "chain": {
            "chain_start": str(chain_start),
            "measurement_start": str(measurement_start),
            "segment_year": int(axis["segment_year"]),
            "end_session": str(end_session),
            "session_hash": canonical_dataset.session_hash(end_session),
            "expected_pointer": int(expected_pointer),
            "canonical_prefix_sha256": _canonical_prefix_hash(
                sessions, expected_pointer, canonical_dataset.session_hash
            ),
            "next_session": axis["next_session"],
            "next_session_hash": (
                None
                if axis["next_session"] is None
                else canonical_dataset.session_hash(axis["next_session"])
            ),
            "previous_checkpoint_sha256": previous_checkpoint_sha256,
        },
        "states": {
            "scaffold": {"state": state_a_dict, "state_hash": str(state_a.state_hash)},
            "production": {"state": state_b_dict, "state_hash": str(state_b.state_hash)},
        },
        "accounts": {
            "scaffold": _account_payload(accounts["A"], "scaffold"),
            "production": _account_payload(accounts["B"], "production"),
        },
        "raw_bookkeeping": {
            "prior_split_factor": dict(
                sorted((str(key), float(value)) for key, value in prior_split_factor.items())
            ),
            "seen_count": dict(
                sorted((str(key), int(value)) for key, value in seen_count.items())
            ),
            "prior_signal_close": dict(
                sorted(
                    (str(key), [int(value[0]), float(value[1])])
                    for key, value in prior_signal_close.items()
                )
            ),
            "latest_ticker_by_sid": dict(
                sorted((str(key), str(value)) for key, value in latest_ticker_by_sid.items())
            ),
            "scaffold_prior_core_close": (
                None if scaffold_prior_core_close is None else float(scaffold_prior_core_close)
            ),
        },
        "module_state": {
            "fullstack": {
                "production_prior_core_close": (
                    None
                    if getattr(fullstack_module, "_pit_prior_core_close", None) is None
                    else float(fullstack_module._pit_prior_core_close)
                ),
                "production_core_by_session": history_rows,
                "pit_metadata_observations": int(
                    getattr(fullstack_module, "_pit_metadata_observations", -1)
                ),
                "pit_sec_cik_observations": int(
                    getattr(fullstack_module, "_pit_sec_cik_observations", -1)
                ),
            },
            "strict": {
                "anchor_issuer_stats": dict(
                    sorted((str(key), int(value)) for key, value in strict_stats.items())
                )
            },
            "progress": {
                "progress_sessions": int(
                    getattr(progress_module, "_progress_sessions", -1)
                )
            },
        },
        "daily": {
            "columns": list(DAILY_COLUMNS),
            "rows": encoded_daily,
            "prefix_sha256": daily_prefix_hash(DAILY_COLUMNS, encoded_daily),
        },
    }
    validate_payload(
        payload,
        expected_identities=identities,
        dataset_hash=str(canonical_dataset.dataset_hash),
        manifest_sha256=canonical_manifest_sha256,
        chain_start=chain_start,
        measurement_start=measurement_start,
        current_end_session=None,
        sessions=sessions,
        session_hash=canonical_dataset.session_hash,
        strict_keys=tuple(strict_stats),
        allow_unlinked_equivalence=allow_unlinked_equivalence,
    )
    return payload


def restore_payload(
    payload: Mapping,
    *,
    identities: Mapping,
    canonical_dataset,
    canonical_manifest_sha256: str,
    chain_start: str,
    measurement_start: str,
    current_end_session: str,
    SessionState,
    OverlayAccount,
    fullstack_module,
    strict_module,
    progress_module,
) -> dict:
    sessions = [str(value) for value in canonical_dataset.sessions]
    strict_stats = getattr(strict_module, "_anchor_issuer_stats", None)
    if not isinstance(strict_stats, dict):
        raise RuntimeError("strict issuer authority counters are unavailable")
    daily_rows = validate_payload(
        payload,
        expected_identities=identities,
        dataset_hash=str(canonical_dataset.dataset_hash),
        manifest_sha256=canonical_manifest_sha256,
        chain_start=chain_start,
        measurement_start=measurement_start,
        current_end_session=current_end_session,
        sessions=sessions,
        session_hash=canonical_dataset.session_hash,
        strict_keys=tuple(strict_stats),
    )
    boundary = payload["chain"]["end_session"]
    states = {}
    for role in ROLE_TO_INTERNAL:
        entry = payload["states"][role]
        state = SessionState.from_dict(entry["state"])
        if str(state.last_processed_session) != boundary:
            raise RuntimeError(f"production checkpoint {role} state/session mismatch")
        if str(state.state_hash) != entry["state_hash"]:
            raise RuntimeError(f"production checkpoint {role} state hash failed after restore")
        states[role] = state
    accounts = {
        role: _restore_account(OverlayAccount, payload["accounts"][role], role)
        for role in ROLE_TO_INTERNAL
    }

    fullstack = payload["module_state"]["fullstack"]
    fullstack_module._pit_prior_core_close = float(
        fullstack["production_prior_core_close"]
    )
    fullstack_module._pit_core_by_session = {
        str(row[0]): (
            None if row[1] is None else float(row[1]),
            float(row[2]),
        )
        for row in fullstack["production_core_by_session"]
    }
    fullstack_module._pit_metadata_observations = fullstack[
        "pit_metadata_observations"
    ]
    fullstack_module._pit_sec_cik_observations = fullstack[
        "pit_sec_cik_observations"
    ]
    for key, value in payload["module_state"]["strict"]["anchor_issuer_stats"].items():
        strict_module._anchor_issuer_stats[key] = value
    progress_module._progress_sessions = payload["module_state"]["progress"][
        "progress_sessions"
    ]

    raw = payload["raw_bookkeeping"]
    return {
        "state_a": states["scaffold"],
        "state_b": states["production"],
        "accounts": {"A": accounts["scaffold"], "B": accounts["production"]},
        "prior_split_factor": dict(raw["prior_split_factor"]),
        "seen_count": dict(raw["seen_count"]),
        "prior_signal_close": {
            key: (value[0], value[1]) for key, value in raw["prior_signal_close"].items()
        },
        "latest_ticker_by_sid": dict(raw["latest_ticker_by_sid"]),
        "prior_core_close": float(raw["scaffold_prior_core_close"]),
        "daily_rows": daily_rows,
        "expected_pointer": payload["chain"]["expected_pointer"],
        "resume_after": boundary,
    }


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def transformed_main_source(runner) -> str:
    """Return the frozen runner ``main`` with narrow checkpoint seams installed."""
    text = textwrap.dedent(inspect.getsource(runner.main))
    text = _replace_once(
        text,
        """        canonical_dataset = CanonicalPITDataset(
            Path(canonical_path), expected_start=CHAIN_START, expected_end=END_SESSION
        )
""",
        """        canonical_dataset = CanonicalPITDataset(
            Path(canonical_path), expected_start=CHAIN_START,
            expected_end=_checkpoint_full_dataset_end,
        )
""",
        "full canonical dataset identity",
    )
    text = _replace_once(
        text,
        """        sessions = list(canonical_dataset.sessions)
""",
        """        _checkpoint_all_sessions = [str(value) for value in canonical_dataset.sessions]
        _checkpoint_segment_axis = _checkpoint_validate_segment_axis(
            _checkpoint_all_sessions, chain_start=CHAIN_START, segment_end=END_SESSION
        )
        sessions = [value for value in _checkpoint_all_sessions if value <= END_SESSION]
        if not sessions or sessions[-1] != END_SESSION:
            raise RuntimeError(
                f'canonical PIT prefix does not end at requested session {END_SESSION}: '
                f'{sessions[-1] if sessions else None}'
            )
""",
        "canonical prefix session axis",
    )

    loop_anchor = """    original_session_breadth = production.session_breadth
    for session, group_iter in itertools.groupby(normalized, key=lambda row: row.vendor.session):
        if session < CHAIN_START:
            continue
"""
    loop_replacement = """    original_session_breadth = production.session_breadth
    _checkpoint_input = os.environ.get('PRODUCTION_RESUME_CHECKPOINT', '').strip()
    _checkpoint_output = os.environ.get('PRODUCTION_CHECKPOINT_OUTPUT', '').strip()
    _checkpoint_unlinked_equivalence = (
        os.environ.get('PRODUCTION_EQUIVALENCE_UNINTERRUPTED', '').strip() == '1'
    )
    if _checkpoint_contract_markers != (
        'production_core_by_session',
        'canonical_prefix_sha256',
        'daily_prefix_sha256',
        'previous_checkpoint_sha256',
    ):
        raise RuntimeError('production checkpoint format contract markers changed')
    _resume_after = None
    _checkpoint_input_sha256 = None
    if canonical_dataset is None:
        raise RuntimeError('production annual checkpointing requires canonical PIT input')
    _checkpoint_manifest_sha256 = sha256_file(canonical_dataset.root / 'manifest.json')
    _checkpoint_identities = _checkpoint_current_identities(
        experiment=EXPERIMENT_ID,
        production_main_sha=EXPECTED_MAIN_SHA,
        checkpoint_module_sha256=_checkpoint_module_sha256,
    )
    _fullstack_module = _checkpoint_fullstack_module
    _strict_module = _checkpoint_strict_module
    _progress_module = _checkpoint_progress_module

    if _checkpoint_input:
        _checkpoint_path = Path(_checkpoint_input).resolve()
        _checkpoint_input_sha256 = _checkpoint_sha256_file(_checkpoint_path)
        _checkpoint_payload = _checkpoint_load(_checkpoint_path)
        _restored = _checkpoint_restore(
            _checkpoint_payload,
            identities=_checkpoint_identities,
            canonical_dataset=canonical_dataset,
            canonical_manifest_sha256=_checkpoint_manifest_sha256,
            chain_start=CHAIN_START,
            measurement_start=_checkpoint_measurement_start,
            current_end_session=END_SESSION,
            SessionState=SessionState,
            OverlayAccount=OverlayAccount,
            fullstack_module=_fullstack_module,
            strict_module=_strict_module,
            progress_module=_progress_module,
        )
        state_a = _restored['state_a']
        state_b = _restored['state_b']
        accounts = _restored['accounts']
        prior_split_factor = defaultdict(lambda: 1.0, _restored['prior_split_factor'])
        seen_count = defaultdict(int, _restored['seen_count'])
        prior_signal_close = _restored['prior_signal_close']
        latest_ticker_by_sid = _restored['latest_ticker_by_sid']
        prior_core_close = _restored['prior_core_close']
        daily_rows = _restored['daily_rows']
        expected_pointer = _restored['expected_pointer']
        _resume_after = _restored['resume_after']
        print(
            f'[CHECKPOINT RESUME] role=Production through={_resume_after} '
            f'sessions={expected_pointer:,} sha256={_checkpoint_input_sha256}',
            flush=True,
        )
    elif (
        _checkpoint_segment_axis['segment_year'] != _checkpoint_genesis_year
        and not _checkpoint_unlinked_equivalence
    ):
        raise RuntimeError('non-genesis production segment requires a predecessor checkpoint')

    for session, group_iter in itertools.groupby(normalized, key=lambda row: row.vendor.session):
        if session < CHAIN_START:
            continue
        if _resume_after is not None and session <= _resume_after:
            continue
"""
    text = _replace_once(
        text, loop_anchor, loop_replacement, "production checkpoint resume boundary"
    )

    finish_anchor = """    production.session_breadth = original_session_breadth
    if expected_pointer != len(sessions):
"""
    finish_replacement = """    production.session_breadth = original_session_breadth
    if _checkpoint_output:
        if expected_pointer != len(sessions):
            raise RuntimeError('cannot checkpoint an incomplete production segment')
        _checkpoint_payload = _checkpoint_build(
            identities=_checkpoint_identities,
            canonical_dataset=canonical_dataset,
            canonical_manifest_sha256=_checkpoint_manifest_sha256,
            chain_start=CHAIN_START,
            measurement_start=_checkpoint_measurement_start,
            end_session=END_SESSION,
            expected_pointer=expected_pointer,
            previous_checkpoint_sha256=_checkpoint_input_sha256,
            state_a=state_a,
            state_b=state_b,
            accounts=accounts,
            prior_split_factor=prior_split_factor,
            seen_count=seen_count,
            prior_signal_close=prior_signal_close,
            latest_ticker_by_sid=latest_ticker_by_sid,
            scaffold_prior_core_close=prior_core_close,
            daily_rows=daily_rows,
            fullstack_module=_fullstack_module,
            strict_module=_strict_module,
            progress_module=_progress_module,
            allow_unlinked_equivalence=_checkpoint_unlinked_equivalence,
        )
        _checkpoint_path = Path(_checkpoint_output).resolve()
        _checkpoint_hash = _checkpoint_write(_checkpoint_path, _checkpoint_payload)
        print(
            f'[CHECKPOINT WRITE] role=Production through={END_SESSION} '
            f'sessions={expected_pointer:,} sha256={_checkpoint_hash} '
            f'path={_checkpoint_path}',
            flush=True,
        )
    if expected_pointer != len(sessions):
"""
    text = _replace_once(
        text, finish_anchor, finish_replacement, "production checkpoint write boundary"
    )
    text = _replace_once(
        text,
        """    daily = pd.DataFrame(daily_rows)
""",
        """    daily = pd.DataFrame(daily_rows, columns=list(_checkpoint_daily_columns))
""",
        "ordered cumulative daily output",
    )
    return text


def install(
    runner,
    *,
    fullstack_module,
    strict_module,
    progress_module,
    measurement_start: str,
) -> None:
    """Replace ``runner.main`` with the authenticated checkpointed variant."""
    for label, module in (
        ("full-stack", fullstack_module),
        ("strict", strict_module),
        ("progress", progress_module),
    ):
        if module is None:
            raise RuntimeError(f"production checkpoint {label} state owner is missing")
    checkpoint_module_sha256 = sha256_file(Path(__file__).resolve())
    runner._checkpoint_full_dataset_end = FULL_DATASET_END
    runner._checkpoint_genesis_year = GENESIS_YEAR
    runner._checkpoint_daily_columns = DAILY_COLUMNS
    runner._checkpoint_contract_markers = CHECKPOINT_CONTRACT_MARKERS
    runner._checkpoint_measurement_start = str(measurement_start)
    runner._checkpoint_module_sha256 = checkpoint_module_sha256
    runner._checkpoint_fullstack_module = fullstack_module
    runner._checkpoint_strict_module = strict_module
    runner._checkpoint_progress_module = progress_module
    runner._checkpoint_current_identities = current_identities
    runner._checkpoint_validate_segment_axis = validate_segment_axis
    runner._checkpoint_sha256_file = sha256_file
    runner._checkpoint_load = load_checkpoint
    runner._checkpoint_restore = restore_payload
    runner._checkpoint_build = build_payload
    runner._checkpoint_write = write_checkpoint
    text = transformed_main_source(runner)
    compile(text, "<checkpointed-production-runner-main>", "exec")
    exec(text, runner.__dict__)
    if runner.main.__module__ != runner.__name__:
        raise RuntimeError("checkpointed production main bound to wrong module")
