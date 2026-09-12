"""Owner-selected compact champion: broad V5, ramp-free native and REC8."""
from dataclasses import asdict, replace
import hashlib
import json

from stock_strategy_shared.wealth_core import v5
from . import median5

STRATEGY_ID = "sentinel-compact-champion-v1"
REFERENCE_SOURCE_SHA256 = "3fcf274dc5dba5b01ff3c637b62922f27c5dfe2e3b28e7f3a416e1bfeba09663"
R40_FLOOR = -0.04
RECOVERY_SESSIONS = 8


def enabled(identity):
    return identity.get("strategy") == STRATEGY_ID


def load():
    base = median5.load()
    config = replace(base, strategy_id=STRATEGY_ID)
    payload = {"native": asdict(config), "wealth_core": asdict(v5.config()),
               "reference_source_sha256": REFERENCE_SOURCE_SHA256,
               "native_schema": "ramp-free-native/1",
               "recovery_schema": "ramp-free-ex3-rebound-false/1",
               "universe": "BROAD_SHARADAR_COMMON_EQUITY",
               "r40_floor": R40_FLOOR, "rec_sessions": RECOVERY_SESSIONS}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    return replace(config, digest=digest)


def recover(**kwargs):
    from .champion import recover as transition
    return transition(**kwargs)
