from pathlib import Path

source_path = Path("tools/issue213-review-fixes.py")
source = source_path.read_text(encoding="utf-8")

# The differential has two REFUSED-report branches (typed refusal and generic
# exception). The original bootstrap deliberately required unique replacements,
# so it stopped before touching source when it encountered both. For this one
# known repeated block, let replace_once replace both and make the later
# one-remaining-occurrence cleanup a zero-occurrence assertion/no-op.
old_helper = '''    if count != 1:\n        raise SystemExit(f"{path}: expected one replacement, found {count}: {old[:100]!r}")\n    p.write_text(text.replace(old, new, 1), encoding="utf-8")\n'''
new_helper = '''    if count not in (1, 2):\n        raise SystemExit(f"{path}: expected one/two replacement(s), found {count}: {old[:100]!r}")\n    p.write_text(text.replace(old, new, count), encoding="utf-8")\n'''
if source.count(old_helper) != 1:
    raise SystemExit("issue213 patcher helper shape changed")
source = source.replace(old_helper, new_helper, 1)

old_tail = '''if text.count(old) != 1:\n    raise SystemExit("differential: expected one remaining REFUSED report fragment")\np.write_text(text.replace(old, new, 1), encoding="utf-8")\n'''
new_tail = '''if text.count(old) != 0:\n    raise SystemExit("differential: REFUSED report fragments were not both replaced")\np.write_text(text, encoding="utf-8")\n'''
if source.count(old_tail) != 1:
    raise SystemExit("issue213 differential cleanup shape changed")
source = source.replace(old_tail, new_tail, 1)

exec(compile(source, str(source_path), "exec"), {"__name__": "__main__"})
