"""Retained EX3 V6 profile: broad V5, R40 strictly above -4%, REC8."""
from dataclasses import asdict, replace
import hashlib
import json

from stock_strategy_shared.wealth_core import v5
from . import median5

STRATEGY_ID = "sentinel-ex3-v6-r40-m04-rec8"
R40_FLOOR = -0.04
RECOVERY_SESSIONS = 8


def enabled(identity):
    from .champion_config import STRATEGY_ID as CHAMPION_ID
    return identity.get("strategy") in (STRATEGY_ID, CHAMPION_ID)


def load():
    base = median5.load()
    config = replace(base, strategy_id=STRATEGY_ID)
    payload = {"native": asdict(config), "wealth_core": asdict(v5.config()),
               "reference_source_sha256": v5.REFERENCE_SOURCE_SHA256,
               "universe": "BROAD_SHARADAR_COMMON_EQUITY",
               "r40_floor": R40_FLOOR, "rec_sessions": RECOVERY_SESSIONS}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    return replace(config, digest=digest)


def recover(**kwargs):
    return median5.recover(**kwargs, r40_floor=R40_FLOOR,
                           rec_sessions=RECOVERY_SESSIONS)
