import json
from pathlib import Path
from sentinel.core import spinoffs
from sentinel.core.decision import data_semantics_source_identity

current = data_semantics_source_identity()
original = spinoffs.__file__
try:
    spinoffs.__file__ = '/baseline/spinoffs.py'
    previous = data_semantics_source_identity()
finally:
    spinoffs.__file__ = original
assert current['sha256'] != previous['sha256']
before = {item['module']: item['sha256'] for item in previous['files']}
after = {item['module']: item['sha256'] for item in current['files']}
changed = [module for module in before if before[module] != after[module]]
assert changed == ['sentinel.core.spinoffs'], changed
Path('/evidence/source-identity.json').write_text(json.dumps({
    'result': 'PASS', 'changed_modules': changed,
    'previous_data_semantics': previous['sha256'],
    'current_data_semantics': current['sha256'],
    'source_sha256': after['sentinel.core.spinoffs'],
    'baseline_sha256': before['sentinel.core.spinoffs'],
}, indent=2) + '\n')
print('PASS: only the spin-off source changes the data-semantics identity')
