from __future__ import annotations

from pathlib import Path
import subprocess

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


@pytest.mark.parametrize("fault", ["duplicate", "invalid-path", "too-few-rolling", "empty-shard"])
def test_invalid_inventory_refuses_instead_of_skipping(fault, monkeypatch):
    modules = _inventory()
    if fault == "duplicate":
        modules.append(modules[0])
    elif fault == "invalid-path":
        modules.append("tests/sentinel/nested/test_hidden.py")
    elif fault == "too-few-rolling":
        modules = [name for name in modules if "test_rolling_" not in name]
    else:
        monkeypatch.setattr(shards.hashlib, "sha256", lambda value: type(
            "SameHash", (), {"digest": lambda self: b"\x00" * 32})())
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
    'test_activation_startup_contention.py', 'test_automation_generation.py'])
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
