from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
SOURCE = (ROOT / "tools" / "corpus_parity.py").read_text()


def test_real_canonical_parity_checks_volume_epoch_before_loading_bars():
    start = SOURCE.index("with engine.connect() as bt_conn")
    end = SOURCE.index("except (bt.RawPriceDomainUnavailable", start)
    body = SOURCE[start:end]
    generation = body.index("FROM bt_data_version WHERE id = 1")
    epoch = body.index("bt.assert_raw_price_domain")
    bars = body.index("bt.load_bars")
    assert generation < epoch < bars
    assert "isinstance(bt_conn, sa.engine.Connection)" in body


def test_parity_names_semantic_epoch_failure_separately_from_identity():
    assert '"price_volume_domain"' in SOURCE
    assert "bt.RawPriceDomainUnavailable" in SOURCE


def test_bt_engine_image_carries_the_facade_dependency_closure():
    dockerfile = (REPO / "services" / "bt-engine" / "Dockerfile").read_text()
    assert "wealth_core_replay.py ./app/live/" in dockerfile
    assert "wealth_core_replay_impl.py ./app/live/" in dockerfile
