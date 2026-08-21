from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


paper = Path("sentinel/paper.py")
text = paper.read_text(encoding="utf-8")

replace_once(
    "sentinel/paper.py",
    "from sentinel.controller.frozen_rule import ControllerConfig, load as load_controller\nfrom sentinel.controller.machine import Controller\n",
    "from sentinel.controller.concordance_parent import load as load_concordance_parent\nfrom sentinel.controller.frozen_rule import ControllerConfig, load as load_controller\nfrom sentinel.controller.ldrc import (\n    LDRCConfig, STRATEGY_ID as LDRC_STRATEGY_ID,\n    STRATEGY_VERSION as LDRC_STRATEGY_VERSION,\n)\nfrom sentinel.controller.machine import Controller\n",
)

replace_once(
    "sentinel/paper.py",
    'DEFENSIVE_SYMBOL = "BIL"\n\n\nclass PaperActivationRefused',
    '''DEFENSIVE_SYMBOL = "BIL"\nSIMPLIFIED_LDRC_STRATEGY_ID = "sentinel-concordance-simplified-ldrc"\nSIMPLIFIED_LDRC_STRATEGY_VERSION = 3\n\n\ndef _default_paper_strategy() -> tuple[ControllerConfig, dict[str, str]]:\n    """Return the one paper-trial strategy: hardened parent + simplified LD-RC.\n\n    The assertions are intentionally redundant with source identity. They make\n    an accidental rollback to the older five-condition/legacy recovery model a\n    startup refusal instead of a plausible but different trading strategy.\n    """\n    if (LDRC_STRATEGY_ID != SIMPLIFIED_LDRC_STRATEGY_ID\n            or LDRC_STRATEGY_VERSION != SIMPLIFIED_LDRC_STRATEGY_VERSION):\n        raise PaperActivationRefused(\n            "paper runtime requires Simplified Concordance LD-RC v3")\n    cfg = LDRCConfig()\n    expected = (0.55, -0.10, -0.08, 0.00, 7, 0.11)\n    actual = (\n        cfg.divergence_ceiling, cfg.wc_drawdown_trigger,\n        cfg.recent_r20_trigger, cfg.spy_r20_floor,\n        cfg.recovery_sessions, cfg.spy_v_rebound,\n    )\n    if actual != expected:\n        raise PaperActivationRefused(\n            "Simplified LD-RC v3 constants differ from the retained strategy")\n    controller = load_concordance_parent()\n    identity = runtime_strategy_identity(controller, concordance=True)\n    if (identity.get("allocation_overlay") != SIMPLIFIED_LDRC_STRATEGY_ID\n            or identity.get("allocation_overlay_version")\n            != str(SIMPLIFIED_LDRC_STRATEGY_VERSION)):\n        raise PaperActivationRefused(\n            "paper strategy identity does not name Simplified LD-RC v3")\n    return controller, identity\n\n\nclass PaperActivationRefused''',
)

replace_once(
    "sentinel/paper.py",
    '''def _validate_broker_grant(conn, grant, _operation: BrokerOperation,\n                           result, *, now_provider) -> None:''',
    '''def _validate_broker_grant(conn, grant, _operation: BrokerOperation,\n                           result, *, now_provider, strategy_provider) -> None:''',
)
replace_once(
    "sentinel/paper.py",
    '''    runtime_strategy = runtime_strategy_identity(load_controller())\n''',
    '''    runtime_strategy = dict(strategy_provider())\n''',
)
replace_once(
    "sentinel/paper.py",
    '''            _validate_broker_grant(\n                fresh, current_grant, operation, result,\n                now_provider=now_provider)),''',
    '''            _validate_broker_grant(\n                fresh, current_grant, operation, result,\n                now_provider=now_provider,\n                strategy_provider=strategy_provider)),''',
)

replace_once(
    "sentinel/paper.py",
    '''    config = controller_config or load_controller()\n    identity = dict(strategy_identity or runtime_strategy_identity(config))\n''',
    '''    if controller_config is None and strategy_identity is None:\n        config, identity = _default_paper_strategy()\n    else:\n        # Preserve the explicit injection seam used by deterministic tests and\n        # administrative tooling. Production supplies neither override.\n        config = controller_config or load_controller()\n        identity = dict(strategy_identity or runtime_strategy_identity(config))\n''',
)
replace_once(
    "sentinel/paper.py",
    '''            strategy_provider = (\n                (lambda: runtime_strategy_identity(load_controller()))\n                if controller_config is None and strategy_identity is None\n                else lambda: dict(identity))\n''',
    '''            strategy_provider = (\n                (lambda: _default_paper_strategy()[1])\n                if controller_config is None and strategy_identity is None\n                else lambda: dict(identity))\n''',
)

# The execution/recovery/inspection paths have no strategy injection seam and\n# therefore must all independently derive the same Simplified LD-RC identity.\nfor old, new, expected_count in [\n    ("        strategy_identity = runtime_strategy_identity(load_controller())\n",\n     "        _controller_config, strategy_identity = _default_paper_strategy()\n", 1),\n    ("        strategy = runtime_strategy_identity(load_controller())\n",\n     "        _controller_config, strategy = _default_paper_strategy()\n", 1),\n    ("    runtime_identity = runtime_strategy_identity(load_controller())\n",\n     "    _controller_config, runtime_identity = _default_paper_strategy()\n", 1),\n]:\n    current = paper.read_text(encoding="utf-8")\n    if current.count(old) != expected_count:\n        raise SystemExit(\n            f"sentinel/paper.py: expected {expected_count} occurrence(s) of {old!r}, "\n            f"found {current.count(old)}")\n    paper.write_text(current.replace(old, new, expected_count), encoding="utf-8")\n
current = paper.read_text(encoding="utf-8")
old = '''                strategy_provider=lambda: runtime_strategy_identity(\n                    load_controller()),\n'''
if current.count(old) != 2:
    raise SystemExit(
        "sentinel/paper.py: expected exactly two execution/recovery strategy providers")
paper.write_text(
    current.replace(
        old,
        '''                strategy_provider=lambda: _default_paper_strategy()[1],\n''',
        2),
    encoding="utf-8",
)

# There must be no unguarded production default left. load_controller remains\n# only for the explicit test/admin injection compatibility branch above.\ncurrent = paper.read_text(encoding="utf-8")
if "runtime_strategy_identity(load_controller())" in current:
    raise SystemExit("sentinel/paper.py still contains a legacy runtime strategy default")

Path("tests/sentinel/test_issue209_simplified_ldrc_runtime.py").write_text(
    '''from sentinel import paper\nfrom sentinel.controller.concordance_parent import (\n    FAST_DAMAGED_BREADTH_DELTA5, STRATEGY_ID as PARENT_STRATEGY_ID,\n)\nfrom sentinel.controller.ldrc import LDRCConfig\n\n\ndef test_default_paper_runtime_is_simplified_three_signal_ldrc_v3():\n    config, identity = paper._default_paper_strategy()  # noqa: SLF001\n    assert config.strategy_id == PARENT_STRATEGY_ID\n    assert config.fast_entry["min_damaged_breadth_delta5"] == FAST_DAMAGED_BREADTH_DELTA5 == 0.30\n    assert identity["strategy"] == PARENT_STRATEGY_ID\n    assert identity["allocation_overlay"] == "sentinel-concordance-simplified-ldrc"\n    assert identity["allocation_overlay_version"] == "3"\n    assert identity["allocation_overlay_source_sha256"]\n    assert identity["recent_leadership_source_sha256"]\n\n\ndef test_simplified_v3_entry_and_recovery_constants_are_frozen():\n    cfg = LDRCConfig()\n    assert (\n        cfg.divergence_ceiling,\n        cfg.wc_drawdown_trigger,\n        cfg.recent_r20_trigger,\n        cfg.spy_r20_floor,\n        cfg.recovery_sessions,\n        cfg.spy_v_rebound,\n    ) == (0.55, -0.10, -0.08, 0.00, 7, 0.11)\n\n\ndef test_paper_gateway_has_no_legacy_runtime_identity_default():\n    source = open(paper.__file__, encoding="utf-8").read()\n    assert "runtime_strategy_identity(load_controller())" not in source\n    assert source.count("_default_paper_strategy()") >= 6\n''',
    encoding="utf-8",
)
