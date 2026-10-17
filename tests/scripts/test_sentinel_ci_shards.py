from __future__ import annotations

from pathlib import Path
import subprocess
import json

import pytest

from tools import sentinel_ci_shards as shards


def _inventory() -> list[str]:
    root = Path(__file__).resolve().parents[2]
    return [f"tests/sentinel/{path.name}" for path in (root / "tests/sentinel").glob("test_*.py")]


def test_shards_are_deterministic_disjoint_and_cover_future_modules():
    modules = _inventory() + ["tests/sentinel/test_future_ordinary.py",
                              "tests/sentinel/test_rolling_future.py"]
    first = shards.plan(modules)
    assert first == shards.plan(list(reversed(modules)))
    assert set(first) == {f"sentinel-{family}-{index}"
                          for family in ("general", "rolling") for index in range(4)}
    selected = [module for group in first.values() for module in group]
    special = {module for module in modules if Path(module).name in shards.SPECIAL}
    assert len(selected) == len(set(selected))
    assert set(selected) == set(modules) - special
    assert all(first.values())
    assert "tests/sentinel/test_future_ordinary.py" in selected
    assert "tests/sentinel/test_rolling_future.py" in selected
    assert all("test_rolling_" not in module for index in range(4)
               for module in first[f"sentinel-general-{index}"])
    assert all("test_rolling_" in module for index in range(4)
               for module in first[f"sentinel-rolling-{index}"])


@pytest.mark.parametrize("fault", ["duplicate", "invalid-path", "too-few-rolling", "changed-shards"])
def test_invalid_inventory_refuses_instead_of_skipping(fault, monkeypatch):
    modules = _inventory()
    if fault == "duplicate":
        modules.append(modules[0])
    elif fault == "invalid-path":
        modules.append("tests/sentinel/nested/test_hidden.py")
    elif fault == "too-few-rolling":
        modules = [name for name in modules if "test_rolling_" not in name]
    else:
        monkeypatch.setattr(shards, "SHARDS", 5)
    with pytest.raises(ValueError, match="duplicated|invalid|too few|incomplete"):
        shards.plan(modules)


def test_tracked_inventory_rejects_untracked_and_symlinked_modules(tmp_path):
    tests = tmp_path / "tests/sentinel"
    tests.mkdir(parents=True)
    (tests / "test_one.py").write_text("pass\n", encoding="utf-8")
    (tests / "test_untracked.py").write_text("pass\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "tests/sentinel/test_one.py"], cwd=tmp_path, check=True)
    assert shards.tracked_modules(tmp_path) == ["tests/sentinel/test_one.py"]
    (tests / "test_one.py").unlink()
    (tests / "test_one.py").symlink_to("test_untracked.py")
    with pytest.raises(ValueError, match="invalid tracked"):
        shards.tracked_modules(tmp_path)


@pytest.mark.parametrize('module', [
    'test_activation_startup_contention.py', 'test_automation_generation.py',
    'test_automation_clock_sampling.py'])
def test_new_automation_boundaries_have_one_coverage_owner(module):
    modules = _inventory()
    startup = "tests/sentinel/" + module
    automation = shards.automation_modules(modules)
    ordinary = [module for lane in shards.plan(modules).values() for module in lane]
    assert automation.count(startup) == 1
    assert startup not in ordinary
    assert set(automation).isdisjoint(ordinary)
    assert automation == shards.automation_modules(list(reversed(modules)))


def test_missing_registered_automation_module_refuses_instead_of_running_a_subset():
    modules = _inventory()
    modules.remove("tests/sentinel/test_activation_startup_contention.py")
    with pytest.raises(ValueError, match="missing registered automation"):
        shards.automation_modules(modules)


def test_measured_costs_balance_both_existing_families_without_dropping_modules():
    groups = shards.plan(_inventory())
    weights, default = shards.load_durations()
    for family, allowed_spread in (("general", 1000), ("rolling", 5000)):
        costs = [sum(weights.get(name, default) for name in groups[f"sentinel-{family}-{i}"])
                 for i in range(shards.SHARDS)]
        assert max(costs) - min(costs) <= allowed_spread


def test_both_families_assign_measured_heavy_modules_to_distinct_workers(monkeypatch):
    modules = [f"tests/sentinel/test_{prefix}case_{i:02d}.py"
               for prefix in ("", "rolling_") for i in range(12)]
    heavy = {name for name in modules if name.endswith(("00.py", "04.py", "08.py", "09.py"))}
    weights = {name: 1000 if name in heavy else 1 for name in modules}
    monkeypatch.setattr(shards, "load_durations", lambda: (weights, 60))
    groups = shards.plan(modules)
    for family in ("general", "rolling"):
        assert all(sum(name in heavy for name in groups[f"sentinel-{family}-{i}"]) == 1
                   for i in range(4))
    assert groups == shards.plan(list(reversed(modules)))


def test_unit_weight_regression_is_an_executed_falsifier(monkeypatch):
    original = shards.plan
    def unit_weights(modules):
        with monkeypatch.context() as isolated:
            isolated.setattr(shards, "load_durations", lambda: ({name: 1 for name in modules}, 1))
            return original(modules)
    monkeypatch.setattr(shards, "plan", unit_weights)
    with pytest.raises(AssertionError):
        test_both_families_assign_measured_heavy_modules_to_distinct_workers(monkeypatch)


def test_new_modules_have_a_positive_conservative_automatic_estimate():
    weights, default = shards.load_durations()
    assert default == 60000
    assert weights.get("tests/sentinel/test_future_case.py", default) > 0


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "10"])
def test_invalid_duration_estimates_refuse_instead_of_changing_partition(tmp_path, bad):
    value = json.loads(shards.DURATIONS.read_text())
    value["modules"][next(iter(value["modules"]))] = bad
    target = tmp_path / "durations.json"
    target.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="module duration"):
        shards.load_durations(target)


def test_duplicate_duration_keys_refuse(tmp_path):
    target = tmp_path / "durations.json"
    target.write_text('{"schema": 1, "schema": 2}')
    with pytest.raises(ValueError, match="duplicate duration"):
        shards.load_durations(target)
