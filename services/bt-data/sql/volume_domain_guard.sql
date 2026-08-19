
-- ── Sharadar SEP volume semantic epoch (2026-08-19) ─────────────────────────
--
-- Pre-#185 bt_prices.volume stores Sharadar's split-adjusted source quantity.
-- Current Wealth Core expects volume in the raw/as-traded share domain so that
-- close_unadjusted * volume == SEP.close * SEP.volume.  The numeric column alone
-- cannot reveal which interpretation produced an existing row.
--
-- Existing rows therefore receive NO default marker.  A full SEP re-backfill
-- through the post-fix bt-data writer rewrites each price row; the trigger below
-- stamps only those post-migration writes.  While bt_data_version is PUBLISHING,
-- the one serialized writer may still read legacy rows in order to replace them.
-- In READY state any attempt to consume an unmarked row raises rather than
-- silently running a backtest on mixed/old liquidity semantics.
ALTER TABLE bt_prices ADD COLUMN IF NOT EXISTS volume_domain_version TEXT;

CREATE OR REPLACE FUNCTION bt_stamp_price_volume_domain() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.volume_domain_version := 'sharadar-raw-volume-v1'; RETURN NEW; END $$;
DROP TRIGGER IF EXISTS trg_bt_stamp_price_volume_domain ON bt_prices;
CREATE TRIGGER trg_bt_stamp_price_volume_domain BEFORE INSERT OR UPDATE OF volume, close, close_unadjusted ON bt_prices FOR EACH ROW EXECUTE FUNCTION bt_stamp_price_volume_domain();

CREATE OR REPLACE FUNCTION bt_price_volume_domain_readable(domain TEXT) RETURNS BOOLEAN LANGUAGE plpgsql VOLATILE AS $$ BEGIN IF domain = 'sharadar-raw-volume-v1' THEN RETURN TRUE; END IF; IF EXISTS (SELECT 1 FROM bt_data_version WHERE id=1 AND status='PUBLISHING') THEN RETURN TRUE; END IF; RAISE EXCEPTION 'bt_prices contains pre-#185/unknown volume-domain rows; run the complete SEP price re-backfill before historical Wealth Core/replay is trusted' USING ERRCODE='22000'; END $$;

ALTER TABLE bt_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE bt_prices FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bt_prices_select_volume_domain ON bt_prices;
CREATE POLICY bt_prices_select_volume_domain ON bt_prices FOR SELECT USING (bt_price_volume_domain_readable(volume_domain_version));
DROP POLICY IF EXISTS bt_prices_insert_volume_domain ON bt_prices;
CREATE POLICY bt_prices_insert_volume_domain ON bt_prices FOR INSERT WITH CHECK (volume_domain_version = 'sharadar-raw-volume-v1');
DROP POLICY IF EXISTS bt_prices_update_volume_domain ON bt_prices;
CREATE POLICY bt_prices_update_volume_domain ON bt_prices FOR UPDATE USING (TRUE) WITH CHECK (volume_domain_version = 'sharadar-raw-volume-v1');
DROP POLICY IF EXISTS bt_prices_delete_volume_domain ON bt_prices;
CREATE POLICY bt_prices_delete_volume_domain ON bt_prices FOR DELETE USING (TRUE);
