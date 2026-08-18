from pathlib import Path

path = Path("tools/issue160_worker.py")
text = path.read_text(encoding="utf-8")
replacements = {
    'path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\\n",':
        'path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\\\\n",',
    'print("\\nDEPLOYMENT PASS: exact Sentinel runtime is installed and durably fenced")':
        'print("\\\\nDEPLOYMENT PASS: exact Sentinel runtime is installed and durably fenced")',
}
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit(f"expected one occurrence of {old!r}, found {text.count(old)}")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
