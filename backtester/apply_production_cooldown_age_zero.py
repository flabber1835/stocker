#!/usr/bin/env python3
"""Apply Issue #294 to an exact pinned production checkout.

This mutates only the checkout path supplied by the diagnostic workflow.  The
repository's ``main`` branch and the pinned production commit remain unchanged.
Every replacement is exact and single-use so source drift fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

EXPECTED_BLOBS = {
    "shared/stock_strategy_shared/wealth_core/state.py":
        "94ba764c79cb7e40d4448195029ecc4c45b8d632",
    "shared/stock_strategy_shared/wealth_core/adapter.py":
        "a59075507c8031dc0f30f1b989ad7253ad4c1715",
}


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True
    ).strip()


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{label}: expected exactly one source match, found {count}"
        )
    return text.replace(old, new, 1)


def apply(root: Path) -> dict:
    root = root.resolve()
    observed = {
        path: _git(root, "hash-object", path) for path in EXPECTED_BLOBS
    }
    if observed != EXPECTED_BLOBS:
        raise SystemExit(
            "production cooldown overlay preimage mismatch: "
            + json.dumps({"expected": EXPECTED_BLOBS, "observed": observed},
                         sort_keys=True)
        )

    state_path = root / "shared/stock_strategy_shared/wealth_core/state.py"
    state = state_path.read_text()
    state = _replace_once(
        state,
        "from typing import TYPE_CHECKING, Any, Mapping\n",
        "from typing import TYPE_CHECKING, AbstractSet, Any, Mapping\n",
        label="state typing import",
    )
    state = _replace_once(
        state,
        '''    def age_one_session(self, split_adjusted_closes: dict[str, float]) -> None:\n        """Advance every clock by one completed session.\n\n        Order matters and is fixed: holdings age and ratchet first, then\n        cooldowns. Both use the same "strictly after the event" convention\n        documented in the module docstring.\n        """\n        for e in self.episodes.values():\n            e.observe_close(split_adjusted_closes.get(e.security_id))\n        for s in self.slots.values():\n            s.age_cooldown()\n        for sid in list(self.security_cooldowns):\n            self.security_cooldowns[sid] += 1\n            if self.security_cooldowns[sid] >= COOLDOWN_SESSIONS:\n                del self.security_cooldowns[sid]\n        self.session_index += 1\n''',
        '''    def age_one_session(\n            self,\n            split_adjusted_closes: dict[str, float],\n            *,\n            skip_slot_cooldowns: AbstractSet[int] = frozenset(),\n            skip_security_cooldowns: AbstractSet[str] = frozenset(),\n            ) -> None:\n        """Advance every clock by one completed session.\n\n        Order matters and is fixed: holdings age and ratchet first, then\n        cooldowns. Both use the same "strictly after the event" convention\n        documented in the module docstring.\n\n        Cooldowns created during this same session are named by the caller and\n        remain at age 0. Their first completed session strictly after the exit\n        is the next market close. The default ages every cooldown, preserving\n        the direct state-machine API for callers that are already operating at\n        a strictly-after-event close.\n        """\n        for e in self.episodes.values():\n            e.observe_close(split_adjusted_closes.get(e.security_id))\n        for slot_id, slot in self.slots.items():\n            if slot_id not in skip_slot_cooldowns:\n                slot.age_cooldown()\n        for security_id in list(self.security_cooldowns):\n            if security_id in skip_security_cooldowns:\n                continue\n            self.security_cooldowns[security_id] += 1\n            if self.security_cooldowns[security_id] >= COOLDOWN_SESSIONS:\n                del self.security_cooldowns[security_id]\n        self.session_index += 1\n''',
        label="PortfolioState.age_one_session",
    )
    state_path.write_text(state)

    adapter_path = root / "shared/stock_strategy_shared/wealth_core/adapter.py"
    adapter = adapter_path.read_text()
    adapter = _replace_once(
        adapter,
        '''    by_sec = {b.security_id: b for b in bars}\n    res_cancelled: list[dict] = []\n\n    # ── 0. re-label ──────────────────────────────────────────────────────────\n''',
        '''    by_sec = {b.security_id: b for b in bars}\n    res_cancelled: list[dict] = []\n    # Snapshot cooldowns that already existed before this session's events.\n    # A terminal action or pending exit below can create a new cooldown. Under\n    # the locked convention, the event session's own close is age 0, so those\n    # new clocks must not advance in step 5.\n    slot_cooldowns_at_session_start = {\n        slot_id for slot_id, slot in state.slots.items()\n        if slot.cooldown_sessions_elapsed is not None}\n    security_cooldowns_at_session_start = set(state.security_cooldowns)\n\n    # ── 0. re-label ──────────────────────────────────────────────────────────\n''',
        label="step_session cooldown snapshot",
    )
    adapter = _replace_once(
        adapter,
        '''    signal_closes = {b.security_id: b.signal_close_split_adj_div_unadj for b in bars}\n    aged = {sid: ep for sid, ep in state.episodes.items()\n            if sid not in entered_this_session}\n    saved, state.episodes = state.episodes, aged\n    state.age_one_session(signal_closes)\n    state.episodes = saved\n''',
        '''    signal_closes = {b.security_id: b.signal_close_split_adj_div_unadj for b in bars}\n    aged = {sid: ep for sid, ep in state.episodes.items()\n            if sid not in entered_this_session}\n    new_slot_cooldowns = {\n        slot_id for slot_id, slot in state.slots.items()\n        if slot.cooldown_sessions_elapsed is not None\n    } - slot_cooldowns_at_session_start\n    new_security_cooldowns = (\n        set(state.security_cooldowns) - security_cooldowns_at_session_start\n    )\n    saved, state.episodes = state.episodes, aged\n    state.age_one_session(\n        signal_closes,\n        skip_slot_cooldowns=new_slot_cooldowns,\n        skip_security_cooldowns=new_security_cooldowns,\n    )\n    state.episodes = saved\n''',
        label="step_session cooldown aging",
    )
    adapter_path.write_text(adapter)

    postimage = {
        path: _git(root, "hash-object", path) for path in EXPECTED_BLOBS
    }
    diff = _git(root, "diff", "--",
                "shared/stock_strategy_shared/wealth_core/state.py",
                "shared/stock_strategy_shared/wealth_core/adapter.py")
    if not diff:
        raise SystemExit("production cooldown overlay produced no diff")
    subprocess.check_call(["git", "-C", str(root), "diff", "--check"])

    return {
        "schema": "backtester.production-cooldown-overlay/1",
        "issue": 294,
        "preimage_blobs": observed,
        "postimage_blobs": postimage,
        "diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "economic_rule": (
            "cooldown age counts closes strictly after the exit session; "
            "the exit-session close is age 0"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    evidence = apply(args.root)
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
