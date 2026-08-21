from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, addition: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if addition in text:
        return
    if marker not in text:
        raise SystemExit(f"{path}: append marker missing")
    p.write_text(text.replace(marker, marker + addition, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Execution certificate identity must name the transport actually used.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/authority.py",
    '        "adapter": "sentinel.execution.alpaca.AlpacaExecutionBroker",\n',
    '        "adapter": "sentinel.execution.alpaca_asset_id.AssetIdAlpacaExecutionBroker",\n',
)

# ---------------------------------------------------------------------------
# 2. Separate historical deterministic integration parity from PIT causality.
#    Production keeps session-effective metadata by default.  Only the explicit
#    certification differential opts into current published metadata, and it
#    labels that historical causality is NOT claimed.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/core/production.py",
    '''def load_published_session(conn, session: str, *, spy_sessions: int = 41,\n                           known_feed_security_ids: Sequence[str] = ()\n                           ) -> PublishedSession:\n    """Load one coherent production input snapshot from the published corpus."""\n''',
    '''def load_published_session(conn, session: str, *, spy_sessions: int = 41,\n                           known_feed_security_ids: Sequence[str] = (),\n                           session_effective_metadata: bool = True\n                           ) -> PublishedSession:\n    """Load one coherent production input snapshot from the published corpus.\n\n    Production planning leaves ``session_effective_metadata`` at its default\n    True, so category/issuer/sector observations after ``session`` are excluded.\n    The historical Concordance *integration* differential explicitly passes\n    False because a fresh seed contains only the current TICKERS observation;\n    that mode proves code-path parity only and makes no historical causality\n    claim. It must never be used by live/catch-up planning.\n    """\n''',
)
replace_once(
    "sentinel/core/production.py",
    '    meta = load_meta(conn, as_of=session)\n',
    '    metadata_as_of = session if session_effective_metadata else None\n    meta = load_meta(conn, as_of=metadata_as_of)\n',
)
replace_once(
    "sentinel/core/production.py",
    '        sectors = load_sectors(conn, as_of=session)\n',
    '        sectors = load_sectors(conn, as_of=metadata_as_of)\n',
)

replace_once(
    "tools/sentinel_concordance_differential.py",
    '''"""No-oracle deterministic differential for Simplified Concordance LD-RC v3.\n\nBoth sides receive the same pinned Sharadar/Wealth-Core/native-parent inputs.\nThe production side is :func:`sentinel.core.production.advance_state`.  The\nreference side below is deliberately handwritten from the retained strategy\nformula and imports neither ``recent_leadership`` nor ``ldrc`` nor the\nproduction Concordance integration module.  No historical expected-allocation\nCSV or session tape is read.\n"""\n''',
    '''"""No-oracle deterministic integration differential for Simplified LD-RC v3.\n\nBoth sides receive the same pinned Sharadar/Wealth-Core/native-parent inputs.\nThe production side is :func:`sentinel.core.production.advance_state`. The\nreference side below is deliberately handwritten from the retained strategy\nformula and imports neither ``recent_leadership`` nor ``ldrc`` nor the\nproduction Concordance integration module. No historical expected-allocation\nCSV or session tape is read.\n\nA fresh certification seed has one *current* TICKERS observation, not historical\npoint-in-time TICKERS snapshots back to 1998. Therefore this tool uses the\ncurrent published metadata projection on BOTH sides to prove historical\nintegration parity and explicitly reports ``historical_metadata_causality`` as\n``NOT_CLAIMED``. Live and outage/catch-up production does the opposite: it keeps\n``load_published_session``'s session-effective metadata default and refuses a\nmissed decision when no causal TICKERS observation exists. Keeping those claims\nseparate prevents a deterministic integration test from laundering current\nmetadata into a historical causality certification.\n"""\n''',
)
replace_once(
    "tools/sentinel_concordance_differential.py",
    '''                published = load_published_session(\n                    conn, session, spy_sessions=REQUIRED_SPY_SESSIONS,\n                    known_feed_security_ids=_known_ids(state))\n''',
    '''                published = load_published_session(\n                    conn, session, spy_sessions=REQUIRED_SPY_SESSIONS,\n                    known_feed_security_ids=_known_ids(state),\n                    session_effective_metadata=False)\n''',
)
replace_once(
    "tools/sentinel_concordance_differential.py",
    '''            "reference_kind": "INDEPENDENT_DETERMINISTIC_CODE",\n            "strategy": STRATEGY,\n''',
    '''            "reference_kind": "INDEPENDENT_DETERMINISTIC_CODE",\n            "metadata_mode": "CURRENT_PUBLISHED_SNAPSHOT_FOR_INTEGRATION_PARITY_ONLY",\n            "historical_metadata_causality": "NOT_CLAIMED",\n            "prospective_metadata_causality": "SESSION_EFFECTIVE_RUNTIME_GATE",\n            "strategy": STRATEGY,\n''',
)
replace_once(
    "tools/sentinel_concordance_differential.py",
    '''            "verdict": "FAIL", "oracle_used": False,\n            "reference_kind": "INDEPENDENT_DETERMINISTIC_CODE",\n            "strategy": STRATEGY, "strategy_version": STRATEGY_VERSION,\n''',
    '''            "verdict": "FAIL", "oracle_used": False,\n            "reference_kind": "INDEPENDENT_DETERMINISTIC_CODE",\n            "metadata_mode": "CURRENT_PUBLISHED_SNAPSHOT_FOR_INTEGRATION_PARITY_ONLY",\n            "historical_metadata_causality": "NOT_CLAIMED",\n            "prospective_metadata_causality": "SESSION_EFFECTIVE_RUNTIME_GATE",\n            "strategy": STRATEGY, "strategy_version": STRATEGY_VERSION,\n''',
)
replace_once(
    "tools/sentinel_concordance_differential.py",
    '''            "verdict": "REFUSED", "oracle_used": False,\n            "strategy": STRATEGY, "strategy_version": STRATEGY_VERSION,\n''',
    '''            "verdict": "REFUSED", "oracle_used": False,\n            "metadata_mode": "CURRENT_PUBLISHED_SNAPSHOT_FOR_INTEGRATION_PARITY_ONLY",\n            "historical_metadata_causality": "NOT_CLAIMED",\n            "prospective_metadata_causality": "SESSION_EFFECTIVE_RUNTIME_GATE",\n            "strategy": STRATEGY, "strategy_version": STRATEGY_VERSION,\n''',
)
# The generic exception branch contains the same fragment a second time.
p = Path("tools/sentinel_concordance_differential.py")
text = p.read_text(encoding="utf-8")
old = '''            "verdict": "REFUSED", "oracle_used": False,\n            "strategy": STRATEGY, "strategy_version": STRATEGY_VERSION,\n'''
new = '''            "verdict": "REFUSED", "oracle_used": False,\n            "metadata_mode": "CURRENT_PUBLISHED_SNAPSHOT_FOR_INTEGRATION_PARITY_ONLY",\n            "historical_metadata_causality": "NOT_CLAIMED",\n            "prospective_metadata_causality": "SESSION_EFFECTIVE_RUNTIME_GATE",\n            "strategy": STRATEGY, "strategy_version": STRATEGY_VERSION,\n'''
if text.count(old) != 1:
    raise SystemExit("differential: expected one remaining REFUSED report fragment")
p.write_text(text.replace(old, new, 1), encoding="utf-8")

replace_once(
    "scripts/sentinel-certify.sh",
    'step "8c/9 deterministic Simplified Concordance LD-RC v3 differential"\n',
    'step "8c/9 deterministic Simplified Concordance LD-RC v3 integration differential"\n',
)
replace_once(
    "scripts/sentinel-certify.sh",
    '''if r.get("sessions_compared", 0) <= 0 or r.get("field_comparisons", 0) <= 0:\n    raise SystemExit("differential did not compare any strategy sessions")\nprint(f"  {r['sessions_compared']} sessions, {r['field_comparisons']} fields, zero mismatches")\n''',
    '''if r.get("metadata_mode") != "CURRENT_PUBLISHED_SNAPSHOT_FOR_INTEGRATION_PARITY_ONLY":\n    raise SystemExit("differential metadata mode is ambiguous")\nif r.get("historical_metadata_causality") != "NOT_CLAIMED":\n    raise SystemExit("integration differential may not claim historical metadata causality")\nif r.get("prospective_metadata_causality") != "SESSION_EFFECTIVE_RUNTIME_GATE":\n    raise SystemExit("differential does not name the forward PIT runtime gate")\nif r.get("sessions_compared", 0) <= 0 or r.get("field_comparisons", 0) <= 0:\n    raise SystemExit("differential did not compare any strategy sessions")\nprint(f"  {r['sessions_compared']} sessions, {r['field_comparisons']} fields, zero mismatches")\nprint("  historical metadata causality: NOT CLAIMED; forward catch-up remains session-effective")\n''',
)

# ---------------------------------------------------------------------------
# 3. Panel lifecycle must report the same standing observation semantics as the
#    runtime authority gate. Historical/admin certificate families stay bounded.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/panel/sources.py",
    '''            "  AND c.expires_at > clock_timestamp()"\n''',
    '''            "  AND (c.expires_at > clock_timestamp()"\n            "       OR c.claims->>'authorization_mode'='PAPER_OBSERVATION_ONLY')"\n''',
)

# ---------------------------------------------------------------------------
# 4. Retain stable asset identity for historical broker POSITIONS as well as
#    orders, without changing the core observation table/fingerprint.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/schema.py",
    '''    "sentinel_automation_service_instances": frozenset({\n        "authority_verdict", "authority_detail", "authority_checked_at"}),\n}\n''',
    '''    "sentinel_automation_service_instances": frozenset({\n        "authority_verdict", "authority_detail", "authority_checked_at"}),\n    "sentinel_observation_provenance": frozenset({"positions"}),\n}\n''',
)
replace_once(
    "sentinel/schema.py",
    '''    """CREATE TABLE IF NOT EXISTS sentinel_observation_provenance (\n        observation_seq   BIGINT PRIMARY KEY REFERENCES sentinel_observations(seq),\n        broker            TEXT        NOT NULL,\n        broker_account_id TEXT        NOT NULL,\n        observed_at       TIMESTAMPTZ NOT NULL)""",\n''',
    '''    """CREATE TABLE IF NOT EXISTS sentinel_observation_provenance (\n        observation_seq   BIGINT PRIMARY KEY REFERENCES sentinel_observations(seq),\n        broker            TEXT        NOT NULL,\n        broker_account_id TEXT        NOT NULL,\n        observed_at       TIMESTAMPTZ NOT NULL,\n        positions         JSONB       NOT NULL DEFAULT '[]'::jsonb)""",\n    """ALTER TABLE sentinel_observation_provenance\n        ADD COLUMN IF NOT EXISTS positions JSONB NOT NULL DEFAULT '[]'::jsonb""",\n''',
)
replace_once(
    "sentinel/execution/journal.py",
    '''            cur.execute(\n                "INSERT INTO sentinel_observation_provenance"\n                " (observation_seq,broker,broker_account_id,observed_at)"\n                " VALUES (%s,%s,%s,%s)",\n                (seq, observation.account_identity.broker,\n                 observation.account_identity.account_id,\n                 observation.observed_at))\n''',
    '''            position_identity = [{\n                "security_id": p.instrument.security_id,\n                "symbol": p.instrument.symbol,\n                "broker_instrument_id": p.instrument.broker_id,\n                "quantity": str(p.quantity),\n            } for p in observation.positions]\n            cur.execute(\n                "INSERT INTO sentinel_observation_provenance"\n                " (observation_seq,broker,broker_account_id,observed_at,positions)"\n                " VALUES (%s,%s,%s,%s,%s)",\n                (seq, observation.account_identity.broker,\n                 observation.account_identity.account_id,\n                 observation.observed_at,\n                 json.dumps(position_identity, sort_keys=True)))\n''',
)

# ---------------------------------------------------------------------------
# 5. Tests must model metadata evolution as a NEW published observation, never
#    mutate protected legacy/published history underneath the authority system.
# ---------------------------------------------------------------------------
helper = '''\n\ndef publish_metadata_snapshot(conn, *, snapshot_date: str, sector: str) -> int:\n    """Publish one later TICKERS observation without rewriting prior history."""\n    suffix = snapshot_date.replace("-", "")[-8:]\n    run_id = f"00000000-0000-0000-0000-{suffix.zfill(12)}"\n    with conn.cursor() as cur:\n        cur.execute(\n            "INSERT INTO feed_ingest_runs"\n            " (run_id,kind,status,date_from,date_to,completed_at)"\n            " VALUES (%s,'daily','success',%s,%s,clock_timestamp())",\n            (run_id, snapshot_date, snapshot_date))\n        cur.execute(\n            "INSERT INTO sentinel_universe"\n            " (permaticker,ticker,category,sector,related_tickers,"\n            " first_price_date,last_price_date,is_delisted,snapshot_date,"\n            " last_written_run_id)"\n            " VALUES ('1001','AAA','Domestic Common Stock',%s,NULL,"\n            " '2020-01-01',NULL,FALSE,%s,%s)",\n            (sector, snapshot_date, run_id))\n        cur.execute("SELECT MAX(version) FROM sentinel_corpus_publications")\n        previous = int(cur.fetchone()[0])\n        version = previous + 1\n        cur.execute(\n            "INSERT INTO sentinel_corpus_publications"\n            " (version,previous_version,run_id,window_start,window_end,evidence)"\n            " VALUES (%s,%s,%s,%s,%s,'{}'::jsonb)",\n            (version, previous, run_id, snapshot_date, snapshot_date))\n    conn.commit()\n    return version\n'''
append_once(
    "tests/sentinel/test_paper_observation_authority.py",
    '    connection.close()\n', helper,
)
replace_once(
    "tests/sentinel/test_paper_observation_authority.py",
    '''    with conn.cursor() as cur:\n        cur.execute("UPDATE sentinel_universe SET sector='Changed'")\n    conn.commit()\n    with pytest.raises(authority.AuthorityRefused, match="metadata snapshot"):\n        authority.require_execution_authority(\n            conn, runtime_identity=runtime_identity(), **kwargs)\n    with conn.cursor() as cur:\n        cur.execute("UPDATE sentinel_universe SET sector='Technology'")\n        cur.execute(\n            "UPDATE sentinel_account_binding SET broker_account_id='paper-evil'"\n            " WHERE id=1")\n    conn.commit()\n''',
    '''    current_version = publish_metadata_snapshot(\n        conn, snapshot_date="2026-08-16", sector="Changed")\n    changed_kwargs = {**kwargs, "current_publication_version": current_version}\n    with pytest.raises(authority.AuthorityRefused, match="metadata snapshot"):\n        authority.require_execution_authority(\n            conn, runtime_identity=runtime_identity(), **changed_kwargs)\n    with conn.cursor() as cur:\n        cur.execute(\n            "UPDATE sentinel_account_binding SET broker_account_id='paper-evil'"\n            " WHERE id=1")\n    conn.commit()\n''',
)
replace_once(
    "tests/sentinel/test_paper_observation_authority.py",
    '''        authority.require_execution_authority(\n            conn, runtime_identity=runtime_identity(), **kwargs)\n\n\ndef test_restart_persistence_and_expired_safety_scope''',
    '''        authority.require_execution_authority(\n            conn, runtime_identity=runtime_identity(), **changed_kwargs)\n\n\ndef test_restart_persistence_and_expired_safety_scope''',
)

replace_once(
    "tests/sentinel/test_issue_209_standing_authority.py",
    '''    runtime_identity,\n    sha,\n)\n''',
    '''    runtime_identity,\n    sha,\n    publish_metadata_snapshot,\n)\n''',
)
replace_once(
    "tests/sentinel/test_issue_209_standing_authority.py",
    '''    # A forward trial must accept ordinary future TICKERS evolution once the\n    # normal ingest/publication/readiness path has made it current authority.\n    with conn.cursor() as cur:\n        cur.execute(\n            "UPDATE sentinel_universe SET sector='Industrials',"\n            " snapshot_date='2026-09-30'"\n        )\n    conn.commit()\n\n    standing = require_standing_observation_authority(\n        conn, **_kwargs(document, now=expired))\n''',
    '''    # A forward trial must accept ordinary future TICKERS evolution once the\n    # normal ingest/publication/readiness path has made it current authority.\n    # Model the real path: a new immutable snapshot in a new published run.\n    current_version = publish_metadata_snapshot(\n        conn, snapshot_date="2026-09-30", sector="Industrials")\n\n    kwargs = _kwargs(document, now=expired)\n    kwargs["current_publication_version"] = current_version\n    standing = require_standing_observation_authority(conn, **kwargs)\n''',
)

# ---------------------------------------------------------------------------
# 6. Regression assertions for the corrected integration boundaries.
# ---------------------------------------------------------------------------
append_once(
    "tests/sentinel/test_issue_209_alpaca_asset_id.py",
    '    assert isinstance(broker, AssetIdAlpacaExecutionBroker)\n',
    '''\n\n\ndef test_execution_certificate_identity_names_asset_id_transport():\n    from sentinel.authority import execution_config_identity\n\n    identity = execution_config_identity(paper_base_url=PAPER)\n    assert identity["adapter"] == (\n        "sentinel.execution.alpaca_asset_id.AssetIdAlpacaExecutionBroker")\n''',
)
append_once(
    "tests/sentinel/test_issue209_concordance_differential.py",
    '        raise AssertionError("wrong effective-native source was accepted")\n',
    '''\n\n\ndef test_historical_differential_does_not_claim_pit_metadata_causality():\n    from sentinel.core import production\n\n    signature = inspect.signature(production.load_published_session)\n    assert signature.parameters["session_effective_metadata"].default is True\n    source = Path(diff.__file__).read_text(encoding="utf-8")\n    assert "session_effective_metadata=False" in source\n    assert '"historical_metadata_causality": "NOT_CLAIMED"' in source\n    assert '"prospective_metadata_causality": "SESSION_EFFECTIVE_RUNTIME_GATE"' in source\n''',
)

# Add a DB-backed provenance regression to the existing asset-identity suite.
p = Path("tests/sentinel/test_issue209_asset_identity.py")
text = p.read_text(encoding="utf-8")
if "test_observation_provenance_retains_position_asset_id" not in text:
    text += '''\n\n\ndef test_observation_provenance_retains_position_asset_id():\n    from sentinel import schema\n    from sentinel.execution.contract import BrokerAccountIdentity\n    from sentinel.feed import store as feed_store\n    from tests.support.postgres import _EphemeralPostgres, drop_public_tables\n\n    server = _EphemeralPostgres()\n    try:\n        server.start()\n    except Exception as exc:  # noqa: BLE001\n        pytest.skip(f"ephemeral Postgres unavailable: {exc}")\n    conn = None\n    try:\n        conn = feed_store.connect(server.sync_dsn)\n        drop_public_tables(conn)\n        feed_store.migrate_schema(conn)\n        schema.migrate_schema(conn)\n        observation = BrokerObservation(\n            observed_at=datetime.now(timezone.utc),\n            account_identity=BrokerAccountIdentity("alpaca", "paper-1"),\n            positions=(BrokerPosition(\n                instrument=BrokerInstrument(\n                    security_id="SEC-AAA", symbol="AAA", broker_id="asset-a"),\n                quantity=Decimal("2")),),\n            completeness=Completeness.COMPLETE)\n        seq = journal.record_observation(conn, observation, "RECONCILING")\n        with conn.cursor() as cur:\n            cur.execute(\n                "SELECT positions FROM sentinel_observation_provenance "\n                "WHERE observation_seq=%s", (seq,))\n            positions = cur.fetchone()[0]\n        assert positions == [{\n            "security_id": "SEC-AAA", "symbol": "AAA",\n            "broker_instrument_id": "asset-a", "quantity": "2"}]\n    finally:\n        if conn is not None:\n            conn.close()\n        server.stop()\n'''
    p.write_text(text, encoding="utf-8")

# Source-level panel regression: standing semantics must not drift back to the
# old unconditional expiry predicate.
p = Path("tests/sentinel/test_issue_209_standing_authority.py")
text = p.read_text(encoding="utf-8")
if "test_panel_uses_standing_observation_lifecycle_semantics" not in text:
    text += '''\n\n\ndef test_panel_uses_standing_observation_lifecycle_semantics():\n    import inspect\n    from sentinel.panel import sources\n\n    source = inspect.getsource(sources._authority_lifecycle)  # noqa: SLF001\n    assert "PAPER_OBSERVATION_ONLY" in source\n    assert "c.expires_at > clock_timestamp()" in source\n'''
    p.write_text(text, encoding="utf-8")
