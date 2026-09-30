"""Reviewed data updates must be generic, atomic and subordinate to coverage."""
from __future__ import annotations

import copy
import json
import os

import pytest

from sentinel.feed import source_corrections as data, corrections_cli as cli
from sentinel.feed.correction_model import CorrectionRefused, validate
from sentinel.feed.rolling_contract import digest


@pytest.fixture
def installed_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SENTINEL_PUBLICATION_RECEIPT_KEY", "local-test-receipt-key-" * 3)
    return tmp_path


def addition(base=None, **fields):
    value = copy.deepcopy(base if base is not None else data.bootstrap())
    value["coverage"].append({
        "kind": "SESSION_ABSENCE", "session": "2025-07-07", "permaticker": "1",
        "ticker": "AAA", "category": "Domestic Common Stock", "first_session": "2025-07-07",
        "first_observed": "2025-07-08", "last_session": None,
        "evidence": {"reference": "synthetic independent listing record", "sha256": "c" * 64,
                     "reviewer": "test reviewer"}, **fields})
    return validate(value)


def install(value):
    return cli.install(value, expected_sha256=digest(value),
                       expected_parent=digest(data.installed()), reviewer="local reviewer")


def test_bundled_facts_preserved_and_new_symbol_needs_no_code(installed_state):
    initial = data.installed()
    assert len(initial["coverage"]) == 40
    assert len(initial["cash_authorities"]) == len(initial["disputed_cash_events"]) == 1
    value = addition(ticker="ZZZ", permaticker="9999999")
    assert install(value) == digest(value)
    assert data.installed() == value
    assert data.coverage_exceptions()[("2025-07-07", "9999999")].ticker == "ZZZ"


@pytest.mark.parametrize("failure", ["hash", "parent", "removal", "replacement", "unsigned", "archive", "pointer"])
def test_bad_install_or_retained_state_refuses(installed_state, failure):
    value = addition()
    old = data.installed()
    if failure in {"hash", "parent"}:
        with pytest.raises(CorrectionRefused):
            cli.install(value, expected_sha256="f" * 64 if failure == "hash" else digest(value),
                        expected_parent="f" * 64 if failure == "parent" else digest(old), reviewer="reviewer")
        assert data.installed() == old
        return
    install(value)
    if failure in {"removal", "replacement"}:
        altered = copy.deepcopy(value)
        if failure == "removal":
            altered["coverage"].pop()
        else:
            altered["coverage"][-1]["first_observed"] = "2025-07-09"
        with pytest.raises(CorrectionRefused, match="remove or replace"):
            install(altered)
        assert data.installed() == value
    else:
        path = data.root() / (digest(value) + ".json" if failure == "archive" else "current.json")
        if failure == "pointer":
            path.unlink()
        else:
            envelope = json.loads(path.read_text())
            envelope["installation"]["dataset"]["coverage"][-1]["ticker"] = "WRONG"
            path.write_text(json.dumps(envelope))
        with pytest.raises(CorrectionRefused):
            data.installed()


@pytest.mark.parametrize("first", [False, True])
def test_crash_before_commit_exposes_only_previous_version_and_retry_succeeds(installed_state, monkeypatch, first):
    if not first:
        install(addition())
    old = data.installed()
    new = addition(old, ticker="ZZZ", permaticker="987654")
    replace = os.replace
    def crash(source, destination):
        if str(destination).endswith("current.json"):
            raise OSError("simulated power loss before pointer commit")
        return replace(source, destination)
    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="power loss"):
        install(new)
    assert data.installed() == old
    monkeypatch.setattr(os, "replace", replace)
    install(new)
    assert data.installed() == new


def test_pinned_attempt_ignores_later_install(installed_state):
    old = data.installed()
    with data.using(old):
        install(addition())
        assert data.current() == old
    assert data.current() != old


def test_cash_data_changes_input_evidence_without_changing_strategy_code_identity(installed_state):
    from types import SimpleNamespace
    from sentinel.core.decision import runtime_strategy_identity
    from sentinel.feed.corporate_action_authority import authority_record_sha256
    from sentinel.feed.rolling_contract import PriceWindow
    from sentinel.feed.rolling_source import SharadarSource

    config = SimpleNamespace(strategy_id="sentinel-test", digest="controller-rule")
    code = runtime_strategy_identity(config)
    original = data.bootstrap()
    revised = copy.deepcopy(original)
    record = revised['cash_authorities'][0]
    record['final_cash_amount'] = '1.50'
    record['record_sha256'] = authority_record_sha256(record)
    revised = validate(revised)
    window = PriceWindow.through('2026-09-14')
    before = SharadarSource(window, corrections=original).source_payload()
    after = SharadarSource(window, corrections=revised).source_payload()

    assert digest(before) != digest(after)
    assert before['source_corrections'] == original
    assert after['source_corrections'] == revised
    with data.using(revised):
        assert runtime_strategy_identity(config) == code
    # Existing reviewed economics still cannot be replaced by an attended update.
    with pytest.raises(CorrectionRefused, match="remove or replace"):
        install(revised)


@pytest.mark.parametrize("field,value", [("session", "2025-7-7"), ("ticker", "*"),
                                         ("permaticker", "1 OR TRUE"), ("extra", "ignored?")])
def test_closed_schema_and_exact_keys(installed_state, field, value):
    with pytest.raises(CorrectionRefused):
        addition(**{field: value})


def test_duplicate_keys_and_coverage_records_refuse(installed_state):
    path = installed_state / "input.json"
    path.write_text('{"schema":1,"schema":2}')
    with pytest.raises(CorrectionRefused, match="duplicate"):
        data.read(path)
    value = addition()
    value["coverage"].append(value["coverage"][-1])
    with pytest.raises(CorrectionRefused, match="duplicate"):
        validate(value)


def test_nonblocking_install_lock_and_missing_key_leave_no_active_state(installed_state, monkeypatch):
    import fcntl
    with (installed_state / "source-corrections-v1.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(CorrectionRefused, match="another correction"):
            install(addition())
    monkeypatch.delenv("SENTINEL_PUBLICATION_RECEIPT_KEY")
    with pytest.raises(RuntimeError):
        install(addition())
    assert not data.root().exists()


def test_unsigned_coordinated_rewrite_cannot_become_authority(installed_state):
    value = addition()
    install(value)
    envelope = data.read(data.root() / "current.json")
    envelope["installation"]["dataset"]["coverage"][-1]["ticker"] = "WRONG"
    forged = envelope["installation"]["dataset"]
    encoded = json.dumps(envelope)
    (data.root() / "current.json").write_text(encoded)
    (data.root() / (digest(forged) + ".json")).write_text(encoded)
    with pytest.raises(CorrectionRefused, match="authentication"):
        data.installed()


def test_lost_install_acknowledgement_is_idempotent(installed_state):
    old = digest(data.installed())
    value = addition()
    identity = install(value)
    before = (data.root() / "current.json").read_bytes()
    assert cli.install(value, expected_sha256=identity, expected_parent=old, reviewer="retry") == identity
    assert (data.root() / "current.json").read_bytes() == before
