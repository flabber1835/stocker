from pathlib import Path

paper = Path("sentinel/paper.py")
text = paper.read_text(encoding="utf-8")
old = '''            strategy_provider=lambda: runtime_strategy_identity(\n                load_controller()),\n'''
new = '''            strategy_provider=lambda: _default_paper_strategy()[1],\n'''
count = text.count(old)
if count != 1:
    raise SystemExit(
        f"sentinel/paper.py: expected one recovery legacy provider, found {count}")
text = text.replace(old, new, 1)
if text.count("load_controller()") != 1:
    raise SystemExit(
        "sentinel/paper.py: production must retain exactly one load_controller() "
        "call, the explicit test/admin override seam")
paper.write_text(text, encoding="utf-8")

test = Path("tests/sentinel/test_issue209_simplified_ldrc_runtime.py")
t = test.read_text(encoding="utf-8")
old_test = '''def test_paper_gateway_has_no_legacy_runtime_identity_default():\n    source = open(paper.__file__, encoding="utf-8").read()\n    assert "runtime_strategy_identity(load_controller())" not in source\n    assert source.count("_default_paper_strategy()") >= 6\n'''
new_test = '''def test_paper_gateway_has_no_legacy_runtime_identity_default():\n    source = open(paper.__file__, encoding="utf-8").read()\n    assert "runtime_strategy_identity(load_controller())" not in source\n    assert source.count("load_controller()") == 1\n    assert source.count("_default_paper_strategy()") >= 7\n'''
if t.count(old_test) != 1:
    raise SystemExit("simplified LD-RC runtime test shape changed unexpectedly")
test.write_text(t.replace(old_test, new_test, 1), encoding="utf-8")
