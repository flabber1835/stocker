"""Reduced work must preserve full-source identity and canonical price results."""
from collections import Counter
from contextlib import closing

import pytest

from sentinel.feed import (
    acquisition_parts, rolling_builder as builder, rolling_publisher as publisher,
    rolling_jobs as jobs, rolling_store, source_aliases, symbol_identity,
)
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_rolling_snapshot_publisher import (
    conn, pg, source, enqueue,
)

__all__ = ["conn", "pg", "source"]


def observe_replay(monkeypatch):
    counts = Counter()
    original = builder._rows

    def read(conn, lease, *, tickers=None):
        phase = "all" if tickers is None else "discovery"
        with closing(original(conn, lease, tickers=tickers)) as rows:
            for row in rows:
                counts[phase] += 1
                yield row

    monkeypatch.setattr(builder, "_rows", read)
    return counts


def result_contents(conn, result):
    candidate = result["candidate_id"]
    proof = conn.execute("SELECT validation_sha256 FROM sentinel_snapshot_validations "
                         "WHERE candidate_id=%s", (candidate,)).fetchone()
    # Compare economic outputs and discovery evidence, not job/UUID identities.
    validation = rolling_store.load_evidence(conn, proof[0])
    return (list(rolling_store.read_bars(conn, candidate)),
            list(rolling_store.read_benchmarks(conn, candidate)),
            validation["coverage"], validation["alias_rejections"],
            validation["split_dispositions"])


def test_ordinary_window_drops_one_full_replay_with_identical_result(conn, source, monkeypatch):
    counts = observe_replay(monkeypatch)
    result = publisher.prepare(conn, enqueue(conn))
    actual = result_contents(conn, result)
    assert counts == {"all": 1200}  # Coverage + normalization; no discovery replay.
    counts.clear()
    # Differential oracle: full discovery over the same captured provider inputs.
    monkeypatch.setattr(source_aliases, "discovery_symbols",
                        lambda identity: tuple(r["ticker"] for r in source["TICKERS"]))
    baseline = publisher.prepare(conn, enqueue(conn))
    assert result_contents(conn, baseline) == actual
    assert counts == {"all": 1200, "discovery": 600}


def add_alias(source):
    """A synthetic unanchored label competes with a valid native listing."""
    day = source["TICKERS"][0]["lastpricedate"]
    # Keep the real 99% population guard intact; these synthetic IPOs start today.
    source["TICKERS"].extend(dict(source["TICKERS"][0], ticker=f"EXTRA{i}",
                                  permaticker=str(i + 10), firstpricedate=day)
                              for i in range(98))
    source["SEP"].extend(dict(row, ticker=f"EXTRA{i}")
                          for row in tuple(source["SEP"]) if row["ticker"] == "AAA" and row["date"] == day
                          for i in range(98))
    for kind, contra in (("tickerchangefrom", "AAA"), ("tickerchangeto", "ALIAS")):
        source["ACTIONS"].append(dict(ticker="ALIAS", date=day, action=kind,
                                      value=None, name="synthetic", contraticker=contra,
                                      contraname=None))
    native = next(r for r in source["SEP"] if r["ticker"] == "AAA" and r["date"] == day)
    source["SEP"].append(dict(native, ticker="ALIAS", close="49", closeunadj="98"))
    return day


def discover(rows, identity, *, selective):
    symbols = set(source_aliases.discovery_symbols(identity))
    with closing(builder._coverage(identity, digest(identity.rows))) as coverage:
        for row in rows:
            if not selective or row["ticker"] in symbols:
                coverage.add(row)
        return source_aliases.discover(coverage, identity)


@pytest.mark.parametrize("kind", ["unanchored", "two_native", "third_native", "healed", "reused_symbol"])
def test_discovery_scope_matches_full_oracle_and_reconstruction(source, kind):
    day = add_alias(source)
    if kind == "two_native":
        source["TICKERS"].append(dict(source["TICKERS"][0], ticker="ALIAS"))
    elif kind == "third_native":
        source["TICKERS"].append(dict(source["TICKERS"][0], ticker="OTHER_NATIVE"))
        source["SEP"].append(dict(source["SEP"][-1], ticker="OTHER_NATIVE"))
    elif kind == "healed":
        source["TICKERS"].append(dict(source["TICKERS"][0], ticker="ALIAS",
                                      permaticker="9000", firstpricedate=day))
    elif kind == "reused_symbol":
        source["TICKERS"].append(dict(source["TICKERS"][0], ticker="ALIAS", permaticker="9000",
                                      firstpricedate="2000-01-03", lastpricedate="2000-01-04",
                                      isdelisted="Y"))
    identity = symbol_identity.SymbolProjection(source["TICKERS"], source["ACTIONS"], through=day)
    selected = discover(source["SEP"], identity, selective=True)
    expected = discover(source["SEP"], identity, selective=False)
    assert selected == expected
    if kind == "unanchored":
        assert len(selected["records"]) == 1
    else:
        assert selected["records"] == []
    source_aliases.apply(identity, selected)
    rebuilt = symbol_identity.SymbolProjection(source["TICKERS"], source["ACTIONS"],
                                                through=day, alias_rejections=expected)
    assert identity.evidence == rebuilt.evidence
    assert identity.alias_rows == rebuilt.alias_rows
    assert identity.chains == rebuilt.chains
    for row in source["SEP"]:
        assert identity.resolver().resolve(row["ticker"], row["date"]) == (
            rebuilt.resolver().resolve(row["ticker"], row["date"]))


def test_alias_window_replays_only_affected_labels_then_full_coverage(conn, source, monkeypatch):
    add_alias(source)
    counts = observe_replay(monkeypatch)
    result = publisher.prepare(conn, enqueue(conn))
    actual = result_contents(conn, result)
    assert len(actual[3]["records"]) == 1
    assert counts == {"all": 1398, "discovery": 301}
    monkeypatch.setattr(source_aliases, "discovery_symbols",
                        lambda identity: tuple({r["ticker"] for r in source["SEP"]}))
    counts.clear()
    baseline = publisher.prepare(conn, enqueue(conn))
    assert result_contents(conn, baseline) == actual
    assert counts == {"all": 1398, "discovery": 699}


@pytest.mark.parametrize("change", ["old_price", "split", "metadata_healing", "missing_unrelated"])
def test_next_attempt_rechecks_changed_dependencies(conn, source, monkeypatch, change):
    day = add_alias(source)
    before = result_contents(conn, publisher.prepare(conn, enqueue(conn)))
    if change == "old_price":
        row = source["SEP"][100]
        row.update(open="48", close="49", closeunadj="98")
    elif change == "split":
        for row in source["SEP"]:
            if row["ticker"] == "BBB" and row["date"] == day:
                row.update(open="98", close="100")
        source["ACTIONS"].append(dict(source["ACTIONS"][0], ticker="BBB", date=day,
                                      action="split", value="2"))
    elif change == "metadata_healing":
        source["TICKERS"].append(dict(source["TICKERS"][0], ticker="ALIAS",
                                      permaticker="9000", firstpricedate=day))
    else:
        source["SEP"] = [r for r in source["SEP"]
                         if not (r["ticker"] == "EXTRA0" and r["date"] == day)]
        with pytest.raises(Exception, match="eligible-set"):
            publisher.prepare(conn, enqueue(conn))
        return
    result = publisher.prepare(conn, enqueue(conn))
    after = result_contents(conn, result)
    assert after != before
    if change == "metadata_healing":
        assert after[3]["records"] == []
        assert any(bar.security_id == "9000" for bar in after[0])
    elif change == "split":
        assert next(b for b in after[0] if str(b.session) == day and b.ticker == "BBB").split_ratio == 2
    monkeypatch.setattr(source_aliases, "discovery_symbols",
                        lambda identity: tuple({r["ticker"] for r in source["SEP"]}))
    baseline = publisher.prepare(conn, enqueue(conn))
    assert result_contents(conn, baseline) == after


def retained(conn, source):
    job = enqueue(conn)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    parts = acquisition_parts.Parts(conn, lease)
    name = "SEP.2026-09-01.2026-09-14"
    parts.put(name, {"revision": 1}, prices=source["SEP"][:2], rows=2)
    return parts, name


def test_known_generation_mismatch_does_not_scan_price_payload(conn, source, monkeypatch):
    parts, name = retained(conn, source)
    def no_payload_read(*a, **k):
        pytest.fail("obsolete part was needlessly replayed")
    monkeypatch.setattr(acquisition_parts.store, "streaming_cursor", no_payload_read)
    with pytest.raises(acquisition_parts.SourceRevision):
        parts.get(name, {"revision": 2})


def test_selected_generation_still_verifies_all_retained_prices(conn, source):
    parts, name = retained(conn, source)
    conn.execute("ALTER TABLE sentinel_acquisition_prices DISABLE TRIGGER acquisition_no_update")
    conn.execute("UPDATE sentinel_acquisition_prices SET payload=replace(payload,'10000','90000')")
    conn.execute("ALTER TABLE sentinel_acquisition_prices ENABLE TRIGGER acquisition_no_update")
    conn.commit()
    with pytest.raises(acquisition_parts.PartCorrupt, match="checksum"):
        parts.get(name, {"revision": 1})


def test_mismatched_generation_still_verifies_manifest_identity(conn, source):
    parts, name = retained(conn, source)
    conn.execute("ALTER TABLE sentinel_acquisition_parts DISABLE TRIGGER acquisition_no_update")
    conn.execute("UPDATE sentinel_acquisition_parts SET manifest=jsonb_set(manifest,'{rows}','0')")
    conn.execute("ALTER TABLE sentinel_acquisition_parts ENABLE TRIGGER acquisition_no_update")
    conn.commit()
    with pytest.raises(acquisition_parts.PartCorrupt, match="manifest checksum"):
        parts.get(name, {"revision": 2})
