"""Legacy opt-ins cannot silently replace guards in a new test module."""
from types import SimpleNamespace

import pytest

from sentinel import identity
from sentinel.feed import coherence, store
from tests.sentinel import conftest as fixtures


def request_for(name):
    return SimpleNamespace(module=SimpleNamespace(__name__=name),
                           node=SimpleNamespace(name="test_guard"))


def missing_product_row():
    return {"ticker": "AAA", "permaticker": "1",
            "category": "Domestic Common Stock", "sector": "Technology",
            "firstpricedate": "2020-01-01", "lastpricedate": "2026-09-14",
            "isdelisted": "N", "relatedtickers": ""}


@pytest.mark.parametrize("module", ["test_future_feed_safety",
                                   "test_renamed_feed_schema",
                                   "test_fixture_compatibility"])
def test_new_and_renamed_modules_keep_real_validation(module, monkeypatch):
    guards = (identity.require_feed_producer_identity, store.require_feed_schema,
              coherence.assert_tickers_metadata, coherence.assert_seed_history)
    fixtures._runtime_schema_test_double_compat.__wrapped__(
        request_for(module), monkeypatch)
    assert guards == (identity.require_feed_producer_identity,
                      store.require_feed_schema,
                      coherence.assert_tickers_metadata,
                      coherence.assert_seed_history)
    with pytest.raises(coherence.TickerMetadataIncomplete, match="table=SEP"):
        coherence.assert_tickers_metadata([missing_product_row()])


def test_existing_explicit_opt_in_preserves_legacy_fixture_behavior(monkeypatch):
    assert "test_feed_store" in fixtures._LEGACY_COMPATIBILITY_MODULES
    fixtures._runtime_schema_test_double_compat.__wrapped__(
        request_for("test_feed_store"), monkeypatch)
    row = missing_product_row()
    assert coherence.assert_tickers_metadata([row]) == [row]
    assert store.require_feed_schema is fixtures._legacy_feed_fixture_install
    assert identity.require_feed_producer_identity()["git_commit"] == "a" * 40


@pytest.mark.parametrize("module,guard", [
    ("test_feed_deployment_provenance", "producer"),
    ("test_issue_165_feed_schema_postgres", "schema"),
    ("test_source_seed_warmup", "source"),
])
def test_dedicated_guard_witnesses_remain_unpatched(module, guard, monkeypatch):
    original = {"producer": identity.require_feed_producer_identity,
                "schema": store.require_feed_schema,
                "source": coherence.assert_tickers_metadata}[guard]
    fixtures._runtime_schema_test_double_compat.__wrapped__(
        request_for(module), monkeypatch)
    assert original is {"producer": identity.require_feed_producer_identity,
                        "schema": store.require_feed_schema,
                        "source": coherence.assert_tickers_metadata}[guard]


@pytest.mark.parametrize("text", ["", "test_old.py\ntest_old.py\n",
                                  "../test_old.py\n", "test_*.py\n"])
def test_invalid_registry_refuses_instead_of_enabling_compatibility(tmp_path, text):
    path = tmp_path / "legacy.txt"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="explicit legacy"):
        fixtures._legacy_compatibility_modules(path)


def test_registry_contains_only_existing_explicit_modules():
    current = {path.stem for path in fixtures.HERE.glob("test_*.py")}
    assert fixtures._LEGACY_COMPATIBILITY_MODULES <= current
    assert "test_fixture_compatibility" not in fixtures._LEGACY_COMPATIBILITY_MODULES
