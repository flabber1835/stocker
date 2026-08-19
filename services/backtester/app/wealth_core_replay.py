"""Financial-grade public facade for the retained canonical Wealth Core replay.

The implementation bytes live beside this module as
:mod:`wealth_core_replay_impl`. This thin facade exists so an upgraded code image
cannot silently reinterpret a pre-#185 ``bt_prices.volume`` column as
raw/as-traded shares merely because the numeric column name stayed the same.

The bt-data schema stamps ``volume_domain_version='sharadar-raw-volume-v1'`` only
when a price row is actually rewritten through the corrected provider boundary.
The canonical replay checks that semantic epoch in the SAME query that already
proves raw-close coverage, then delegates every other byte of behavior to the
retained implementation module.

Keeping the old implementation as an exact Git blob is deliberate: this change
adds one database-authority gate; it does not refactor strategy/replay behavior
while repairing data provenance.
"""
from __future__ import annotations

from sqlalchemy import text

from . import wealth_core_replay_impl as _impl

PRICE_VOLUME_DOMAIN = "sharadar-raw-volume-v1"

# Preserve the existing fixture/query discriminator ``COUNT(close_unadjusted)``
# while adding the semantic epoch count. Real SQLAlchemy mappings always expose
# n_legacy; small unit-test fake rows written before this guard may omit the new
# additive field and therefore default it to zero without weakening production.
_COVERAGE_WITH_VOLUME_DOMAIN_SQL = text("""
    SELECT COUNT(*) AS n,
           COUNT(close_unadjusted) AS n_raw,
           COUNT(*) FILTER (
               WHERE volume_domain_version IS DISTINCT FROM
                     'sharadar-raw-volume-v1') AS n_legacy
      FROM bt_prices
     WHERE date BETWEEN :start AND :end
""")


def assert_raw_price_domain(conn, start: str, end: str) -> float:
    """Prove both raw-close presence and the post-#185 volume semantic epoch."""
    try:
        row = conn.execute(
            _COVERAGE_WITH_VOLUME_DOMAIN_SQL,
            {"start": start, "end": end}).mappings().first()
    except Exception as exc:
        raise _impl.RawPriceDomainUnavailable(
            "bt_prices cannot prove its post-#185 volume-domain semantics. "
            "Run `python -m app.volume_domain_migration` in the corrected "
            "bt-data image before historical Wealth Core/replay is trusted.") from exc

    if row is None:
        raise _impl.RawPriceDomainUnavailable(
            f"no bt_prices rows between {start} and {end}")
    n = row["n"] or 0
    n_raw = row["n_raw"] or 0
    n_legacy = row.get("n_legacy", 0) if hasattr(row, "get") else 0
    if n == 0:
        raise _impl.RawPriceDomainUnavailable(
            f"no bt_prices rows between {start} and {end}")
    if n_legacy:
        raise _impl.RawPriceDomainUnavailable(
            f"bt_prices contains {int(n_legacy):,} row(s) between {start} and "
            f"{end} whose volume domain predates or cannot prove "
            f"{PRICE_VOLUME_DOMAIN}. The same numeric `volume` column used to "
            "mean Sharadar split-adjusted shares and now means raw-compatible "
            "as-traded shares; code-version parity cannot distinguish them. "
            "Run `python -m app.volume_domain_migration` in bt-data and do not "
            "repin historical results around an unproven corpus.")

    coverage = n_raw / n
    if coverage < _impl.MIN_RAW_CLOSE_COVERAGE:
        raise _impl.RawPriceDomainUnavailable(
            f"bt_prices.close_unadjusted is populated for {coverage:.1%} of rows "
            f"between {start} and {end}, below the "
            f"{_impl.MIN_RAW_CLOSE_COVERAGE:.0%} floor. Wealth Core marks the "
            "book and fills orders in the AS-TRADED domain; SEP.close is "
            "SPLIT-ADJUSTED and substituting it would value every post-split "
            "holding at the wrong level without failing. Remedy: re-backfill "
            "the bt-data SEP stage, which maps SEP.closeunadj -> "
            "bt_prices.close_unadjusted.")
    return coverage


# Patch the retained function's module global. Python resolves this name when
# run_wealth_core_replay executes, so all canonical full replays cross the new
# semantic boundary without modifying the retained implementation bytes.
_impl.assert_raw_price_domain = assert_raw_price_domain

# Compatibility matters beyond __all__: existing tests/diagnostics import
# constants such as MIN_RAW_CLOSE_COVERAGE and some focused regressions inspect
# private SQL helpers. The old module exposed every imported/defined module
# attribute naturally, so mirror that surface rather than narrowing it as an
# accidental side effect of adding this facade. The patched assertion is already
# installed on _impl, so this copy retains the new gate.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

# These two names belong to the facade, not the retained implementation.
globals()["PRICE_VOLUME_DOMAIN"] = PRICE_VOLUME_DOMAIN
globals()["_COVERAGE_WITH_VOLUME_DOMAIN_SQL"] = _COVERAGE_WITH_VOLUME_DOMAIN_SQL
assert_raw_price_domain = _impl.assert_raw_price_domain
__all__ = list(_impl.__all__)
