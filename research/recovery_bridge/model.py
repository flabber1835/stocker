"""Research-only partial release of a sole leadership recovery hold."""
from datetime import date
import hashlib
import json
import math

RULE = dict(sessions=8, core_r20_above=0., damage_at_most=.63,
            green_at_least=.20, ceiling=.55, reason="FULL_RISK_HELD")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class RecoveryBridge:
    def __init__(self, owned):
        self.owned = owned
        self.streak = 0
        self.last_session = None
        self.identity = digest(dict(schema="owned-recovery-bridge/1", rule=RULE, parent=owned.identity))

    def step(self, row):
        day = row["session"]
        if date.fromisoformat(day).isoformat() != day or (self.last_session is not None and day <= self.last_session):
            raise ValueError("bridge sessions must strictly advance")
        result = self.owned.step(row)
        ob = row["observation"]
        r20, damage, green = (ob.get(k) for k in ("shadow_r20", "damaged_breadth", "green_breadth"))
        healthy = (all(type(x) in (int, float) and math.isfinite(x) for x in (r20, damage, green))
                   and r20 > RULE["core_r20_above"] and damage <= RULE["damage_at_most"]
                   and green >= RULE["green_at_least"])
        self.streak = min(RULE["sessions"], self.streak + 1) if healthy and result["native"] == 1. else 0
        permitted = (self.streak == RULE["sessions"] and result["native"] == 1.
                     and result["base"]["reason"] == RULE["reason"])
        target = result["target"]
        if permitted:
            target = min(RULE["ceiling"], result["native"], result["ceiling"])
        self.last_session = day
        return dict(target=target, native=result["native"], bridge=permitted,
                    healthy=bool(healthy), streak=self.streak, owned=result)

    def snapshot(self):
        result = dict(identity=self.identity, streak=self.streak, last_session=self.last_session,
                      owned=self.owned.snapshot())
        return dict(result, sha256=digest(result))

    def restore(self, value):
        if value.get("identity") != self.identity or value.get("sha256") != digest(
                {k: v for k, v in value.items() if k != "sha256"}):
            raise ValueError("bridge checkpoint identity or commitment changed")
        streak, day = value["streak"], value["last_session"]
        if type(streak) is not int or not 0 <= streak <= RULE["sessions"]:
            raise ValueError("bridge streak invalid")
        if (day is None and streak) or (day is not None and date.fromisoformat(day).isoformat() != day):
            raise ValueError("bridge session invalid")
        if value["owned"].get("last_session") != day:
            raise ValueError("bridge parent session differs")
        self.owned.restore(value["owned"])
        self.streak, self.last_session = streak, day
