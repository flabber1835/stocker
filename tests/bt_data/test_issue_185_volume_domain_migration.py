from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = (ROOT / "services" / "bt-data" / "sql" /
         "volume_domain_guard.sql").read_text()
DOCKERFILE = (ROOT / "services" / "bt-data" / "Dockerfile").read_text()
ENGINE_GATE = (ROOT / "services" / "bt-engine" / "app" /
               "jobs_busy.py").read_text()


def test_runtime_schema_bootstrap_installs_the_semantic_epoch_guard():
    assert "cat ./sql/volume_domain_guard.sql >> ./sql/init_bt.sql" in DOCKERFILE


def test_existing_rows_are_not_blindly_grandfathered_into_new_volume_semantics():
    column_stmt = next(
        line for line in GUARD.splitlines()
        if "ADD COLUMN IF NOT EXISTS volume_domain_version" in line)
    assert "DEFAULT" not in column_stmt.upper()
    assert "sharadar-raw-volume-v1" not in column_stmt


def test_only_post_fix_price_writes_are_stamped():
    assert "bt_stamp_price_volume_domain" in GUARD
    assert "BEFORE INSERT OR UPDATE OF volume, close, close_unadjusted" in GUARD
    assert "NEW.volume_domain_version := 'sharadar-raw-volume-v1'" in GUARD


def test_unknown_domain_rows_have_a_bounded_certification_probe():
    assert "idx_bt_prices_unknown_volume_domain" in GUARD
    assert "WHERE volume_domain_version IS DISTINCT FROM 'sharadar-raw-volume-v1'" in GUARD
    assert "ORDER BY date,ticker LIMIT 1" in ENGINE_GATE


def test_certification_gate_is_explicit_not_row_level_security():
    # docker-compose.backtest.yml uses POSTGRES_USER=btuser; that bootstrap role
    # is a PostgreSQL superuser and would bypass RLS even under FORCE ROW LEVEL
    # SECURITY. The financial-safety property therefore has to be an explicit
    # generation check in bt-engine, not a table policy.
    assert "ROW LEVEL SECURITY" not in GUARD
    assert "_require_price_volume_domain" in ENGINE_GATE
    assert "await _require_price_volume_domain(conn)" in ENGINE_GATE
    assert "pre-#185/unknown volume-domain rows" in ENGINE_GATE
