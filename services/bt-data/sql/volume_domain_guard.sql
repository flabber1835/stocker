
-- ── Sharadar SEP volume semantic epoch (2026-08-19) ─────────────────────────
--
-- Pre-#185 bt_prices.volume stores Sharadar's split-adjusted source quantity.
-- Current Wealth Core expects volume in the raw/as-traded share domain so that
-- close_unadjusted * volume == SEP.close * SEP.volume. The numeric column alone
-- cannot reveal which interpretation produced an existing row.
--
-- Existing rows therefore receive NO default marker. A post-fix bt-data price
-- write stamps the semantic epoch in a trigger, so the marker cannot be faked by
-- merely upgrading application code. The certification engine explicitly refuses
-- any READY corpus containing an unmarked row before its first price query.
--
-- Do NOT use row-level security for this safety property. The compose database
-- role is the PostgreSQL bootstrap role (`POSTGRES_USER=btuser`) and is therefore
-- a superuser on existing deployments; superusers bypass RLS even when FORCE ROW
-- LEVEL SECURITY is enabled. The explicit bt-engine generation gate is not
-- bypassed by role privilege.
ALTER TABLE bt_prices ADD COLUMN IF NOT EXISTS volume_domain_version TEXT;

CREATE OR REPLACE FUNCTION bt_stamp_price_volume_domain() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.volume_domain_version := 'sharadar-raw-volume-v1'; RETURN NEW; END $$;
DROP TRIGGER IF EXISTS trg_bt_stamp_price_volume_domain ON bt_prices;
CREATE TRIGGER trg_bt_stamp_price_volume_domain BEFORE INSERT OR UPDATE OF volume, close, close_unadjusted ON bt_prices FOR EACH ROW EXECUTE FUNCTION bt_stamp_price_volume_domain();

-- The certification gate asks for one unknown row with ORDER BY date,ticker
-- LIMIT 1. This partial index makes that proof cheap even on a 35M-row corpus:
-- existing legacy rows populate it on migration, and each successful post-fix
-- rewrite removes that row from the index. When the index is empty the complete
-- persisted price corpus has crossed the semantic epoch.
CREATE INDEX IF NOT EXISTS idx_bt_prices_unknown_volume_domain
    ON bt_prices (date, ticker)
    WHERE volume_domain_version IS DISTINCT FROM 'sharadar-raw-volume-v1';
