from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = (ROOT / "services" / "bt-data" / "sql" /
         "volume_domain_guard.sql").read_text()
DOCKERFILE = (ROOT / "services" / "bt-data" / "Dockerfile").read_text()


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


def test_legacy_rows_raise_for_readers_but_remain_visible_to_serialized_rebackfill():
    assert "FORCE ROW LEVEL SECURITY" in GUARD
    assert "FOR SELECT USING (bt_price_volume_domain_readable" in GUARD
    assert "status='PUBLISHING'" in GUARD
    assert "run the complete SEP price re-backfill" in GUARD
    assert "RAISE EXCEPTION" in GUARD


def test_new_or_rewritten_rows_cannot_publish_without_the_marker():
    assert "FOR INSERT WITH CHECK (volume_domain_version = 'sharadar-raw-volume-v1')" in GUARD
    assert "FOR UPDATE USING (TRUE) WITH CHECK (volume_domain_version = 'sharadar-raw-volume-v1')" in GUARD
