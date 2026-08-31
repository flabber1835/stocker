from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import backtester as _test_package

_RUNNER_PACKAGE = str(Path(__file__).resolve().parents[2] / "backtester")
if _RUNNER_PACKAGE not in _test_package.__path__:
    _test_package.__path__.append(_RUNNER_PACKAGE)

from backtester import production_year_checkpoint_overlay as checkpoint


SESSIONS = [
    "2006-01-03",
    "2006-12-29",
    "2007-01-03",
    "2007-12-31",
    "2008-01-02",
    checkpoint.FULL_DATASET_END,
]
CHAIN_START = SESSIONS[0]
MEASUREMENT_START = "2006-07-31"
MANIFEST_SHA = hashlib.sha256(b"canonical manifest").hexdigest()
DATASET_SHA = hashlib.sha256(b"canonical dataset").hexdigest()


def _session_hash(session: str) -> str:
    return hashlib.sha256(f"canonical:{session}".encode()).hexdigest()


class _Dataset:
    sessions = SESSIONS
    dataset_hash = DATASET_SHA

    @staticmethod
    def session_hash(session: str) -> str:
        return _session_hash(session)


class _State:
    def __init__(self, raw):
        self.raw = copy.deepcopy(raw)
        self.last_processed_session = str(raw["last_processed_session"])

    @property
    def state_hash(self):
        return checkpoint.hash_value(self.raw)

    def to_dict(self):
        return copy.deepcopy(self.raw)

    @classmethod
    def from_dict(cls, raw):
        return cls(raw)


class _Account:
    def __init__(self, name: str):
        self.name = name
        self.nav = 1.0
        self.effective = 0.0
        self.pending = 0.0
        self.initialized = False
        self.transition_cost = 0.0
        self.transitions = 0


def _daily_row(session: str, index: int) -> dict:
    positions = json.dumps([f"sid-{index}"], separators=(",", ":"))
    return {
        "date": session,
        "A_nav": 1.0 + 0.1 * index,
        "B_nav": 1.0 + 0.2 * index,
        "SPY_level": 1.0 + 0.05 * index,
        "wealth_core_equity": 1.5 + 0.5 * index,
        "A_allocation": 0.0,
        "B_allocation": 0.75,
        "A_native": 0.0,
        "B_native": 1.0,
        "A_damaged": False,
        "B_damaged": True,
        "green": 0.4,
        "D_eligible_universe": 10,
        "D_ranking_count": 1,
        "D_ranking_sha256": hashlib.sha256(f"ranking-{index}".encode()).hexdigest(),
        "D_selected_positions_sha256": hashlib.sha256(positions.encode()).hexdigest(),
        "D_selected_positions": positions,
        "D_intents": json.dumps([], sort_keys=True, separators=(",", ":")),
        "D_ldrc_state": json.dumps(
            {
                "episode": False,
                "latched": False,
                "prev_desired": 0.75,
                "prev_native": 1.0,
                "streak": index,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def _identities() -> dict:
    return {
        "experiment": "production-20y-test",
        "backtester_sha": "1" * 40,
        "production_main_sha": "2" * 40,
        "production_overlay_sha256": "3" * 64,
        "checkpoint_module_sha256": "4" * 64,
    }


def _objects():
    state_a = _State(
        {"last_processed_session": SESSIONS[1], "role": "scaffold", "cash": 1.0}
    )
    state_b = _State(
        {"last_processed_session": SESSIONS[1], "role": "production", "cash": 1.2}
    )
    account_a = _Account("A")
    account_a.nav = 1.1
    account_a.effective = account_a.pending = 0.0
    account_a.initialized = True
    account_b = _Account("B")
    account_b.nav = 1.2
    account_b.effective = account_b.pending = 0.75
    account_b.initialized = True
    account_b.transition_cost = 0.001
    account_b.transitions = 1
    fullstack = SimpleNamespace(
        _pit_prior_core_close=1.75,
        _pit_core_by_session={
            SESSIONS[0]: (None, 1.25),
            SESSIONS[1]: (1.2, 1.75),
        },
        _pit_metadata_observations=20,
        _pit_sec_cik_observations=15,
    )
    strict = SimpleNamespace(
        _anchor_issuer_stats={"anchors": 3, "sec_cik": 2, "unknown_singleton": 1}
    )
    progress = SimpleNamespace(_progress_sessions=2)
    return state_a, state_b, {"A": account_a, "B": account_b}, fullstack, strict, progress


def _payload() -> dict:
    state_a, state_b, accounts, fullstack, strict, progress = _objects()
    rows = [_daily_row(SESSIONS[0], 0), _daily_row(SESSIONS[1], 1)]
    return checkpoint.build_payload(
        identities=_identities(),
        canonical_dataset=_Dataset(),
        canonical_manifest_sha256=MANIFEST_SHA,
        chain_start=CHAIN_START,
        measurement_start=MEASUREMENT_START,
        end_session=SESSIONS[1],
        expected_pointer=2,
        previous_checkpoint_sha256=None,
        state_a=state_a,
        state_b=state_b,
        accounts=accounts,
        prior_split_factor={"sid-1": 1.0},
        seen_count={"sid-1": 2},
        prior_signal_close={"sid-1": (1, 50.0)},
        latest_ticker_by_sid={"sid-1": "ONE"},
        scaffold_prior_core_close=2.0,
        daily_rows=rows,
        fullstack_module=fullstack,
        strict_module=strict,
        progress_module=progress,
    )


def _validate(
    payload: dict,
    *,
    current_end_session: str | None = SESSIONS[3],
    allow_unlinked_equivalence: bool = False,
):
    return checkpoint.validate_payload(
        payload,
        expected_identities=_identities(),
        dataset_hash=DATASET_SHA,
        manifest_sha256=MANIFEST_SHA,
        chain_start=CHAIN_START,
        measurement_start=MEASUREMENT_START,
        current_end_session=current_end_session,
        sessions=SESSIONS,
        session_hash=_session_hash,
        strict_keys=("anchors", "sec_cik", "unknown_singleton"),
        allow_unlinked_equivalence=allow_unlinked_equivalence,
    )


def _rewrite(path: Path, payload: dict) -> None:
    checkpoint.write_checkpoint(path, payload)


def test_format_3_round_trip_restores_every_state_owner(tmp_path):
    payload = _payload()
    path = tmp_path / "production-2006.json"
    digest = checkpoint.write_checkpoint(path, payload)

    assert len(digest) == 64
    assert Path(str(path) + ".sha256").is_file()
    loaded = checkpoint.load_checkpoint(path)
    assert loaded == payload

    fullstack = SimpleNamespace()
    strict = SimpleNamespace(
        _anchor_issuer_stats={"anchors": 0, "sec_cik": 0, "unknown_singleton": 0}
    )
    progress = SimpleNamespace(_progress_sessions=0)
    restored = checkpoint.restore_payload(
        loaded,
        identities=_identities(),
        canonical_dataset=_Dataset(),
        canonical_manifest_sha256=MANIFEST_SHA,
        chain_start=CHAIN_START,
        measurement_start=MEASUREMENT_START,
        current_end_session=SESSIONS[3],
        SessionState=_State,
        OverlayAccount=_Account,
        fullstack_module=fullstack,
        strict_module=strict,
        progress_module=progress,
    )

    assert restored["state_b"].state_hash == payload["states"]["production"]["state_hash"]
    assert restored["accounts"]["B"].nav == 1.2
    assert restored["expected_pointer"] == 2
    assert list(restored["daily_rows"][0]) == list(checkpoint.DAILY_COLUMNS)
    assert list(fullstack._pit_core_by_session) == SESSIONS[:2]
    assert fullstack._pit_prior_core_close == 1.75
    assert strict._anchor_issuer_stats == payload["module_state"]["strict"]["anchor_issuer_stats"]
    assert progress._progress_sessions == 2


def test_daily_arrays_preserve_the_19_column_order_through_sorted_json(tmp_path):
    original = _daily_row(SESSIONS[0], 0)
    reverse_order = {key: original[key] for key in reversed(tuple(original))}
    encoded = checkpoint.encode_daily_rows([reverse_order])
    decoded = checkpoint.decode_daily_rows(list(checkpoint.DAILY_COLUMNS), encoded)
    assert len(checkpoint.DAILY_COLUMNS) == 19
    assert list(decoded[0]) == list(checkpoint.DAILY_COLUMNS)

    payload = _payload()
    path = tmp_path / "checkpoint.json"
    checkpoint.write_checkpoint(path, payload)
    loaded = checkpoint.load_checkpoint(path)
    restored_rows = checkpoint.decode_daily_rows(
        loaded["daily"]["columns"], loaded["daily"]["rows"]
    )
    assert list(restored_rows[0]) == list(checkpoint.DAILY_COLUMNS)


def test_checkpoint_requires_a_valid_complete_file_sidecar(tmp_path):
    path = tmp_path / "checkpoint.json"
    checkpoint.write_checkpoint(path, _payload())
    Path(str(path) + ".sha256").unlink()
    with pytest.raises(RuntimeError, match="sidecar is missing"):
        checkpoint.load_checkpoint(path)

    checkpoint.write_checkpoint(path, _payload())
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="complete-file SHA256 mismatch"):
        checkpoint.load_checkpoint(path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.__setitem__("unexpected", True),
        lambda p: p["identities"].__setitem__("production_overlay_sha256", "5" * 64),
        lambda p: p["chain"].__setitem__("next_session_hash", "6" * 64),
        lambda p: p["chain"].__setitem__("previous_checkpoint_sha256", "7" * 64),
        lambda p: p["accounts"]["production"].__setitem__("pending", 1.01),
        lambda p: p["accounts"]["production"].__setitem__("nav", "1.2"),
        lambda p: p["raw_bookkeeping"]["seen_count"].clear(),
        lambda p: p["module_state"]["fullstack"]["production_core_by_session"][
            0
        ].__setitem__(0, SESSIONS[1]),
        lambda p: p["module_state"]["progress"].__setitem__("progress_sessions", 1),
        lambda p: p["daily"].__setitem__("columns", list(reversed(checkpoint.DAILY_COLUMNS))),
    ],
)
def test_semantic_tampering_is_rejected_even_when_outer_hashes_are_recomputed(mutate):
    payload = copy.deepcopy(_payload())
    mutate(payload)
    with pytest.raises(RuntimeError):
        _validate(payload)


def test_daily_tamper_is_rejected_by_prefix_hash():
    payload = copy.deepcopy(_payload())
    payload["daily"]["rows"][0][1] = 99.0
    with pytest.raises(RuntimeError, match="daily prefix hash mismatch"):
        _validate(payload)


def test_state_hash_is_recomputed_after_from_dict_before_any_module_restore():
    payload = copy.deepcopy(_payload())
    payload["states"]["production"]["state"]["cash"] = 999.0
    fullstack = SimpleNamespace(_pit_prior_core_close="unchanged")
    strict = SimpleNamespace(
        _anchor_issuer_stats={"anchors": 0, "sec_cik": 0, "unknown_singleton": 0}
    )
    progress = SimpleNamespace(_progress_sessions=0)

    with pytest.raises(RuntimeError, match="production state hash failed after restore"):
        checkpoint.restore_payload(
            payload,
            identities=_identities(),
            canonical_dataset=_Dataset(),
            canonical_manifest_sha256=MANIFEST_SHA,
            chain_start=CHAIN_START,
            measurement_start=MEASUREMENT_START,
            current_end_session=SESSIONS[3],
            SessionState=_State,
            OverlayAccount=_Account,
            fullstack_module=fullstack,
            strict_module=strict,
            progress_module=progress,
        )
    assert fullstack._pit_prior_core_close == "unchanged"
    assert progress._progress_sessions == 0


def test_missing_or_extra_account_roles_are_rejected():
    missing = copy.deepcopy(_payload())
    del missing["accounts"]["scaffold"]
    with pytest.raises(RuntimeError, match="accounts fields differ"):
        _validate(missing)

    extra = copy.deepcopy(_payload())
    extra["accounts"]["legacy-D"] = copy.deepcopy(extra["accounts"]["production"])
    with pytest.raises(RuntimeError, match="accounts fields differ"):
        _validate(extra)


def test_unlinked_non_genesis_checkpoint_is_equivalence_only():
    payload = copy.deepcopy(_payload())
    rows = [_daily_row(session, index) for index, session in enumerate(SESSIONS[:4])]
    encoded = checkpoint.encode_daily_rows(rows)
    payload["daily"] = {
        "columns": list(checkpoint.DAILY_COLUMNS),
        "rows": encoded,
        "prefix_sha256": checkpoint.daily_prefix_hash(checkpoint.DAILY_COLUMNS, encoded),
    }
    payload["chain"].update({
        "segment_year": 2007,
        "end_session": SESSIONS[3],
        "session_hash": _session_hash(SESSIONS[3]),
        "expected_pointer": 4,
        "canonical_prefix_sha256": checkpoint.hash_value(
            [[session, _session_hash(session)] for session in SESSIONS[:4]]
        ),
        "next_session": SESSIONS[4],
        "next_session_hash": _session_hash(SESSIONS[4]),
        "previous_checkpoint_sha256": None,
    })
    for role in ("scaffold", "production"):
        state = payload["states"][role]["state"]
        state["last_processed_session"] = SESSIONS[3]
        payload["states"][role]["state_hash"] = checkpoint.hash_value(state)
    payload["accounts"]["scaffold"]["nav"] = rows[-1]["A_nav"]
    payload["accounts"]["production"]["nav"] = rows[-1]["B_nav"]
    payload["raw_bookkeeping"].update({
        "seen_count": {"sid-1": 4},
        "prior_signal_close": {"sid-1": [3, 50.0]},
        "scaffold_prior_core_close": rows[-1]["wealth_core_equity"],
    })
    payload["module_state"]["fullstack"].update({
        "production_prior_core_close": 2.75,
        "production_core_by_session": [
            [session, None if index == 0 else 1.0 + index * 0.5, 1.25 + index * 0.5]
            for index, session in enumerate(SESSIONS[:4])
        ],
    })
    payload["module_state"]["progress"]["progress_sessions"] = 4

    _validate(
        payload,
        current_end_session=None,
        allow_unlinked_equivalence=True,
    )
    with pytest.raises(RuntimeError, match="lacks a predecessor digest"):
        _validate(payload, current_end_session=None)
