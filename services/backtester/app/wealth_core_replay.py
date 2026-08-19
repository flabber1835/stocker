"""Financial-grade public facade for the retained canonical Wealth Core replay.

The implementation bytes live beside this module as
:mod:`wealth_core_replay_impl`. This thin facade exists so an upgraded code image
cannot silently reinterpret a pre-#185 ``bt_prices.volume`` column as
raw/as-traded shares merely because the numeric column name stayed the same.

The bt-data schema creates one durable volume-domain authority singleton. A
legacy populated database starts unproven; the supported migration force-replays
the complete price corpus, proves every row was rewritten through the corrected
provider boundary, and marks the singleton proven in the same transaction that
publishes a new READY data UUID. Any old/undeclared bt-data writer invalidates it
on its first price write.

The canonical replay checks that O(1) authority before delegating raw-close
coverage and every other byte of replay behavior to the retained implementation
module. Keeping that implementation as an exact Git blob is deliberate: this
change adds one database-authority gate; it does not refactor strategy/replay
behavior while repairing data provenance.
"""
from __future__ import annotations

from sqlalchemy import text

from . import wealth_core_replay_impl as _impl

PRICE_VOLUME_DOMAIN = "sharadar-raw-volume-v1"

_PRICE_VOLUME_DOMAIN_SQL = text("""
    SELECT domain_version, proven, note
      FROM bt_price_volume_domain_state
     WHERE id = 1
""")

_ORIGINAL_ASSERT_RAW_PRICE_DOMAIN = _impl.assert_raw_price_domain


def assert_raw_price_domain(conn, start: str, end: str) -> float:
    """Prove the post-#185 volume epoch, then run retained raw-close coverage."""
    try:
        state = conn.execute(_PRICE_VOLUME_DOMAIN_SQL).mappings().first()
    except Exception as exc:
        raise _impl.RawPriceDomainUnavailable(
            "bt-data cannot prove its post-#185 volume-domain semantics. Run "
            "`python -m app.volume_domain_migration` in the corrected bt-data "
            "image before historical Wealth Core/replay is trusted.") from exc

    if state is None:
        raise _impl.RawPriceDomainUnavailable(
            "bt_price_volume_domain_state has no singleton authority row; run "
            "the corrected bt-data schema/migration before replay")
    domain = state["domain_version"]
    proven = state["proven"]
    note = state.get("note") if hasattr(state, "get") else None
    if str(domain) != PRICE_VOLUME_DOMAIN or proven is not True:
        raise _impl.RawPriceDomainUnavailable(
            "bt_prices volume semantics are not proven for this corpus: "
            f"domain={domain!r}, proven={proven!r}, note={note!r}. The same "
            "numeric `volume` column used to mean Sharadar split-adjusted shares "
            "and now means raw-compatible as-traded shares; code-version parity "
            "cannot distinguish them. Run `python -m app.volume_domain_migration` "
            "and do not repin historical results around an unproven corpus.")

    # Preserve the retained implementation's exact raw-close coverage query and
    # error semantics; economic-domain provenance is the only added behavior.
    return _ORIGINAL_ASSERT_RAW_PRICE_DOMAIN(conn, start, end)


# Patch the retained function's module global. Python resolves this name when
# run_wealth_core_replay executes, so all canonical full replays cross the new
# semantic boundary without modifying the retained implementation bytes.
_impl.assert_raw_price_domain = assert_raw_price_domain

# Compatibility matters beyond __all__: existing tests/diagnostics import
# constants and some focused regressions inspect private helpers. Mirror the old
# module surface rather than narrowing it as an accidental side effect of adding
# this facade. The patched assertion is already installed on _impl.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

globals()["PRICE_VOLUME_DOMAIN"] = PRICE_VOLUME_DOMAIN
globals()["_PRICE_VOLUME_DOMAIN_SQL"] = _PRICE_VOLUME_DOMAIN_SQL
globals()["_ORIGINAL_ASSERT_RAW_PRICE_DOMAIN"] = _ORIGINAL_ASSERT_RAW_PRICE_DOMAIN
assert_raw_price_domain = _impl.assert_raw_price_domain
__all__ = list(_impl.__all__)
