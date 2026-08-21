from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# Production loader must have no switch that disables point-in-time metadata.
replace_once(
    "sentinel/core/production.py",
    '''def load_published_session(conn, session: str, *, spy_sessions: int = 41,\n                           known_feed_security_ids: Sequence[str] = (),\n                           session_effective_metadata: bool = True\n                           ) -> PublishedSession:\n    """Load one coherent production input snapshot from the published corpus.\n\n    Production planning leaves ``session_effective_metadata`` at its default\n    True, so category/issuer/sector observations after ``session`` are excluded.\n    The historical Concordance *integration* differential explicitly passes\n    False because a fresh seed contains only the current TICKERS observation;\n    that mode proves code-path parity only and makes no historical causality\n    claim. It must never be used by live/catch-up planning.\n    """\n''',
    '''def load_published_session(conn, session: str, *, spy_sessions: int = 41,\n                           known_feed_security_ids: Sequence[str] = ()\n                           ) -> PublishedSession:\n    """Load one causal production input snapshot from the published corpus.\n\n    Strategy metadata is always bounded to ``session``. There is intentionally\n    no production switch for current/future TICKERS metadata: a missed session\n    either has a causally available observation or planning refuses. Historical\n    integration-only experiments that cannot make that causality claim must\n    override their inputs outside this production API.\n    """\n''')
replace_once(
    "sentinel/core/production.py",
    '''    metadata_as_of = session if session_effective_metadata else None\n    meta = load_meta(conn, as_of=metadata_as_of)\n''',
    '''    meta = load_meta(conn, as_of=session)\n''')
replace_once(
    "sentinel/core/production.py",
    '''        sectors = load_sectors(conn, as_of=metadata_as_of)\n''',
    '''        sectors = load_sectors(conn, as_of=session)\n''')

# Historical integration parity explicitly substitutes current metadata only in
# this tool process. The production loader remains causal-only.
replace_once(
    "tools/sentinel_concordance_differential.py",
    '''from pathlib import Path\nfrom typing import Mapping, Sequence\n\nfrom sentinel.controller.concordance_parent import load as load_concordance_parent\n''',
    '''from pathlib import Path\nfrom typing import Mapping, Sequence\nfrom unittest.mock import patch\n\nfrom sentinel.controller.concordance_parent import load as load_concordance_parent\n''')
replace_once(
    "tools/sentinel_concordance_differential.py",
    '''from sentinel.core.loader import load_window\n''',
    '''from sentinel.core.loader import (\n    load_meta as load_current_meta, load_sectors as load_current_sectors,\n    load_window,\n)\n''')
replace_once(
    "tools/sentinel_concordance_differential.py",
    '''                published = load_published_session(\n                    conn, session, spy_sessions=REQUIRED_SPY_SESSIONS,\n                    known_feed_security_ids=_known_ids(state),\n                    session_effective_metadata=False)\n''',
    '''                # A fresh historical seed has only one current TICKERS\n                # observation. Override metadata strictly inside this audit\n                # process so we can test overlay/integration parity without\n                # creating a production causality bypass. Both sides receive\n                # the same current projection and the report says explicitly\n                # that historical metadata causality is NOT claimed.\n                def current_meta(_conn, *, as_of=None):\n                    return load_current_meta(_conn)\n\n                def current_sectors(_conn, *, as_of=None):\n                    return load_current_sectors(_conn)\n\n                with patch("sentinel.core.loader.load_meta", current_meta), \\\n                     patch("sentinel.core.loader.load_sectors", current_sectors):\n                    published = load_published_session(\n                        conn, session, spy_sessions=REQUIRED_SPY_SESSIONS,\n                        known_feed_security_ids=_known_ids(state))\n''')

# Strengthen the regression: no production bypass parameter may exist.
replace_once(
    "tests/sentinel/test_issue209_concordance_differential.py",
    '''    signature = inspect.signature(production.load_published_session)\n    assert signature.parameters["session_effective_metadata"].default is True\n    source = Path(diff.__file__).read_text(encoding="utf-8")\n    assert "session_effective_metadata=False" in source\n''',
    '''    signature = inspect.signature(production.load_published_session)\n    assert "session_effective_metadata" not in signature.parameters\n    production_source = inspect.getsource(production.load_published_session)\n    assert "load_meta(conn, as_of=session)" in production_source\n    assert "load_sectors(conn, as_of=session)" in production_source\n    source = Path(diff.__file__).read_text(encoding="utf-8")\n    assert 'patch("sentinel.core.loader.load_meta"' in source\n    assert 'patch("sentinel.core.loader.load_sectors"' in source\n''')
