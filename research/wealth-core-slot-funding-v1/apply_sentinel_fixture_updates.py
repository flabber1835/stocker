from pathlib import Path

REPLACEMENTS = {
    Path("tests/sentinel/test_issue209_target_reprojection.py"): (
        '    state.reserve_slot(0, "SEC-A", "AAA", "issuer-a")\n',
        '    state.reserve_slot(0, "SEC-A", "AAA", "issuer-a", 300.30)\n',
    ),
    Path("tests/sentinel/test_production_state.py"): (
        '    portfolio.slots[1].reserve("pending", "PEND", "P:pending")\n',
        '    portfolio.slots[1].reserve("pending", "PEND", "P:pending", 100.0)\n',
    ),
}

for path, (old, new) in REPLACEMENTS.items():
    text = path.read_text()
    count = text.count(old)
    if count == 0:
        if new in text:
            print(f"already migrated: {path}")
            continue
        raise RuntimeError(f"fixture anchor missing in {path}")
    if count != 1:
        raise RuntimeError(f"fixture anchor count={count} in {path}")
    path.write_text(text.replace(old, new, 1))
    print(f"migrated: {path}")
