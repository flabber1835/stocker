"""Offline expected/observed Alpaca PAPER ledger certificate falsifiers."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools import sentinel_paper_ledger_certify as certificate


H = {
    "commit": "a" * 64,
    "account": "b" * 64,
    "plan": "c" * 64,
    "client": "d" * 64,
    "security": "e" * 64,
    "fill": "f" * 64,
}


def _ledger(schema: str, *, captured_at: str) -> dict:
    return {
        "schema": schema,
        "captured_at": captured_at,
        "commit_sha": H["commit"],
        "account_subject_sha256": H["account"],
        "plan_id_sha256": H["plan"],
        "decision_session": "2026-09-03",
        "effective_session": "2026-09-04",
        "cash": "99000.00",
        "equity": "100000.00",
        "positions": {H["security"]: "10"},
        "orders": [{
            "client_key_sha256": H["client"],
            "security_id_sha256": H["security"],
            "side": "BUY",
            "quantity": "10",
            "filled_quantity": "10",
            "filled_average_price": "100",
            "state": "FILLED",
        }],
        "fills": [{
            "fill_sha256": H["fill"],
            "client_key_sha256": H["client"],
            "security_id_sha256": H["security"],
            "quantity": "10",
            "price": "100",
            "filled_at": "2026-09-04T13:30:01+00:00",
        }],
        "corporate_actions": [],
        "completeness": "COMPLETE",
    }


def _write(path, value, *, canonical=True):
    separators = (",", ":") if canonical else None
    path.write_text(
        json.dumps(value, sort_keys=True, separators=separators) + "\n",
        encoding="ascii",
    )


def _pair(tmp_path):
    expected = _ledger(
        certificate.EXPECTED_SCHEMA,
        captured_at="2026-09-04T13:29:59+00:00",
    )
    observed = _ledger(
        certificate.OBSERVED_SCHEMA,
        captured_at="2026-09-04T13:31:00+00:00",
    )
    expected_path = tmp_path / "expected.json"
    observed_path = tmp_path / "observed.json"
    _write(expected_path, expected)
    _write(observed_path, observed)
    return expected, observed, expected_path, observed_path


def test_exact_ledgers_produce_a_deterministic_read_only_match(tmp_path):
    _expected, _observed, expected_path, observed_path = _pair(tmp_path)
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    first = certificate.certify(
        expected_path=expected_path,
        observed_path=observed_path,
        output=first_path,
    )
    second = certificate.certify(
        expected_path=expected_path,
        observed_path=observed_path,
        output=second_path,
    )

    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first["verdict"] == "MATCH"
    assert first["certification_passed"] is True
    assert first["broker_mutation_attempts"] == 0
    assert first["performance_authority"] == "CERTIFIED_SHADOW_ONLY"


@pytest.mark.parametrize(
    ("component", "change"),
    [
        ("cash", lambda value: value.update(cash="98999.98")),
        ("equity", lambda value: value.update(equity="99999.98")),
        ("positions", lambda value: value["positions"].update(
            {H["security"]: "9"})),
        ("orders", lambda value: (
            value["orders"][0].update(
                filled_quantity="9", state="PARTIALLY_FILLED"),
            value["fills"][0].update(quantity="9"),
        )),
        ("fills", lambda value: value["fills"][0].update(price="100.01")),
        ("corporate_actions", lambda value: value["corporate_actions"].append({
            "action_sha256": "4" * 64,
            "security_id_sha256": H["security"],
            "kind": "SPLIT",
            "effective_session": "2026-09-04",
            "quantity_multiplier": "2",
            "cash_amount": "0",
        })),
    ],
)
def test_any_economic_divergence_fails_with_sanitized_subjects(
        tmp_path, component, change):
    _expected, observed, expected_path, observed_path = _pair(tmp_path)
    change(observed)
    _write(observed_path, observed)

    report = certificate.certify(
        expected_path=expected_path,
        observed_path=observed_path,
        output=tmp_path / "report.json",
    )

    assert report["verdict"] == "DIVERGED"
    assert report["certification_passed"] is False
    assert component in {row["component"] for row in report["mismatches"]}
    rendered = json.dumps(report)
    assert "99000.00" not in rendered
    assert "98999.98" not in rendered


def test_one_cent_cash_rounding_is_within_the_fixed_tolerance(tmp_path):
    _expected, observed, expected_path, observed_path = _pair(tmp_path)
    observed["cash"] = "98999.99"
    _write(observed_path, observed)

    report = certificate.certify(
        expected_path=expected_path,
        observed_path=observed_path,
        output=tmp_path / "report.json",
    )

    assert report["verdict"] == "MATCH"


def test_order_and_fill_delivery_order_does_not_change_the_ledger(tmp_path):
    expected, observed, expected_path, observed_path = _pair(tmp_path)
    second_order = {
        **expected["orders"][0],
        "client_key_sha256": "1" * 64,
        "security_id_sha256": "2" * 64,
        "quantity": "3",
        "filled_quantity": "3",
    }
    second_fill = {
        **expected["fills"][0],
        "fill_sha256": "3" * 64,
        "client_key_sha256": "1" * 64,
        "security_id_sha256": "2" * 64,
        "quantity": "3",
    }
    expected["orders"].append(second_order)
    expected["fills"].append(second_fill)
    observed["orders"] = list(reversed(deepcopy(expected["orders"])))
    observed["fills"] = list(reversed(deepcopy(expected["fills"])))
    _write(expected_path, expected)
    _write(observed_path, observed)

    report = certificate.certify(
        expected_path=expected_path,
        observed_path=observed_path,
        output=tmp_path / "report.json",
    )

    assert report["verdict"] == "MATCH"


@pytest.mark.parametrize("damage", ["incomplete", "duplicate", "regressed"])
def test_incomplete_duplicate_or_time_regressed_broker_evidence_refuses(
        tmp_path, damage):
    _expected, observed, expected_path, observed_path = _pair(tmp_path)
    if damage == "incomplete":
        observed["completeness"] = "PARTIAL"
    elif damage == "duplicate":
        observed["fills"].append(deepcopy(observed["fills"][0]))
    else:
        observed["captured_at"] = "2026-09-04T13:29:58+00:00"
    _write(observed_path, observed)

    with pytest.raises(certificate.PaperLedgerRefused):
        certificate.certify(
            expected_path=expected_path,
            observed_path=observed_path,
            output=tmp_path / "report.json",
        )


def test_noncanonical_or_raw_identifier_fields_refuse(tmp_path):
    _expected, observed, expected_path, observed_path = _pair(tmp_path)
    _write(observed_path, observed, canonical=False)
    with pytest.raises(certificate.PaperLedgerRefused, match="unknown shape"):
        certificate.certify(
            expected_path=expected_path,
            observed_path=observed_path,
            output=tmp_path / "report.json",
        )

    observed["account_id"] = "raw-paper-account"
    _write(observed_path, observed)
    with pytest.raises(certificate.PaperLedgerRefused, match="unknown shape"):
        certificate.certify(
            expected_path=expected_path,
            observed_path=observed_path,
            output=tmp_path / "report.json",
        )


@pytest.mark.parametrize("damage", ["orphan-fill", "missing-fill"])
def test_every_fill_has_one_order_origin_and_exact_aggregate(
        tmp_path, damage):
    _expected, observed, expected_path, observed_path = _pair(tmp_path)
    if damage == "orphan-fill":
        observed["fills"][0]["client_key_sha256"] = "9" * 64
    else:
        observed["fills"] = []
    _write(observed_path, observed)

    with pytest.raises(certificate.PaperLedgerRefused):
        certificate.certify(
            expected_path=expected_path,
            observed_path=observed_path,
            output=tmp_path / "report.json",
        )


def test_cli_distinguishes_match_divergence_and_refusal(tmp_path):
    _expected, observed, expected_path, observed_path = _pair(tmp_path)
    output = tmp_path / "report.json"
    args = [
        "--expected", str(expected_path),
        "--observed", str(observed_path),
        "--output", str(output),
    ]
    assert certificate.main(args) == 0

    observed["cash"] = "98000"
    _write(observed_path, observed)
    assert certificate.main(args) == 1

    observed["completeness"] = "PARTIAL"
    _write(observed_path, observed)
    assert certificate.main(args) == 2


def test_certificate_surface_has_no_network_or_broker_mutation_client():
    source = Path(certificate.__file__).read_text(encoding="utf-8")
    for forbidden in ("httpx", "requests", ".post(", ".delete(", ".patch("):
        assert forbidden not in source
    assert '"broker_mutation_attempts": 0' in source
