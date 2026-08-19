
-- ── Sharadar SEP volume semantic epoch (2026-08-19) ─────────────────────────
--
-- Pre-#185 bt_prices.volume stores Sharadar's split-adjusted source quantity.
-- Current Wealth Core expects volume in the raw/as-traded share domain so that
-- close_unadjusted * volume == SEP.close * SEP.volume. The numeric column alone
-- cannot reveal which interpretation produced an existing row.
--
-- Existing rows therefore receive NO default marker. The post-fix bt-data build
-- binds database connections to application_name=bt-data-sharadar-raw-volume-v1.
-- The row trigger stamps only that writer identity. An older/rolled-back binary
-- clears the touched row's marker and, in the same transaction, invalidates the
-- singleton corpus-domain authority below.
--
-- The singleton is the RUNTIME gate. Do not build an index over every legacy row:
-- before migration that index would contain the entire ~35M-row price corpus and
-- make schema bootstrap itself the expensive operation. A legacy deployment is
-- born `proven=false`; a fresh empty database is born `proven=true`. The supported
-- migration force-replays the complete stored SEP range + benchmark prices,
-- performs one explicit full residual scan of volume_domain_version, then sets
-- `proven=true` in the SAME transaction that publishes the new READY data UUID.
--
-- Do NOT use row-level security for this safety property. The compose database
-- role is the PostgreSQL bootstrap role (`POSTGRES_USER=btuser`) and is therefore
-- a superuser on existing deployments; superusers bypass RLS even when FORCE ROW
-- LEVEL SECURITY is enabled.
ALTER TABLE bt_prices ADD COLUMN IF NOT EXISTS volume_domain_version TEXT;

CREATE TABLE IF NOT EXISTS bt_price_volume_domain_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    domain_version  TEXT NOT NULL,
    proven          BOOLEAN NOT NULL,
    proven_at       TIMESTAMPTZ,
    invalidated_at  TIMESTAMPTZ,
    note            TEXT
);

-- On a truly fresh DB there is no legacy semantic ambiguity: every future price
-- row must pass through the installed trigger. Existing populated databases start
-- unproven and cannot be grandfathered by merely installing the schema.
INSERT INTO bt_price_volume_domain_state
    (id, domain_version, proven, proven_at, note)
SELECT 1, 'sharadar-raw-volume-v1',
       NOT EXISTS (SELECT 1 FROM bt_prices),
       CASE WHEN NOT EXISTS (SELECT 1 FROM bt_prices) THEN NOW() ELSE NULL END,
       CASE WHEN NOT EXISTS (SELECT 1 FROM bt_prices)
            THEN 'fresh empty corpus under post-#185 schema'
            ELSE 'legacy populated corpus requires volume-domain migration' END
ON CONFLICT (id) DO NOTHING;

CREATE OR REPLACE FUNCTION bt_stamp_price_volume_domain() RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE writer_name TEXT; BEGIN writer_name := current_setting('application_name', true); IF writer_name = 'bt-data-sharadar-raw-volume-v1' THEN NEW.volume_domain_version := 'sharadar-raw-volume-v1'; ELSE NEW.volume_domain_version := NULL; UPDATE bt_price_volume_domain_state SET proven=FALSE, proven_at=NULL, invalidated_at=NOW(), note='price write from undeclared/pre-#185 writer: ' || COALESCE(writer_name,'<unset>') WHERE id=1; END IF; RETURN NEW; END $$;
DROP TRIGGER IF EXISTS trg_bt_stamp_price_volume_domain ON bt_prices;
CREATE TRIGGER trg_bt_stamp_price_volume_domain BEFORE INSERT OR UPDATE OF volume, close, close_unadjusted ON bt_prices FOR EACH ROW EXECUTE FUNCTION bt_stamp_price_volume_domain();
