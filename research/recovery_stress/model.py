"""Frozen sign-confirmed recovery; exact two-predicate research transform."""
import hashlib
import json
from pathlib import Path

CHANGES = (("recent_r20 >= wc_r20", "recent_r20 > 0"),
           ("spy20 >= wc_r20", "spy20 > 0"))


def transformed(source):
    for before, after in CHANGES:
        if source.count(before) != 1:
            raise ValueError("frozen recovery predicate changed")
        source = source.replace(before, after)
    return source


def probe(parameters):
    from sentinel.controller import champion_frozen
    base = parameters.ProbeController("current")
    changed = transformed(Path(champion_frozen.__file__).read_text(encoding="utf-8"))
    namespace = {"__name__": "sign_confirmed_recovery_research"}
    exec(compile(changed, "<sign-confirmed-candidate>", "exec"), namespace)
    base.Candidate = namespace["CandidateA"]
    base.candidate = base.Candidate()
    identity = dict(schema="sign-confirmed-recovery/1", base=base.identity,
                    transformed_sha256=hashlib.sha256(changed.encode()).hexdigest(), changes=CHANGES)
    base.identity = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return base
