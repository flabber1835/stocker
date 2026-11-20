"""Stable wire values for replay of previously signed books and receipts."""
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

_raw = Path(__file__).with_name('archive-identifiers-v1.json').read_bytes()
if hashlib.sha256(_raw).hexdigest() != 'a70ea0510a5c43d0d71f8cb3ab1478f0036a837c69ace4d067bf9c82e0081e11':
    raise ValueError('Historical wire identifier registry changed')
_values = json.loads(_raw)
BOOK_SCHEMA = _values['BOOK_SCHEMA']
NORMALIZATION = _values['NORMALIZATION']
PROVIDER = _values['PROVIDER']
REFERENCES_SCHEMA = _values['REFERENCES_SCHEMA']
RETIRED_CREDENTIAL = _values['RETIRED_CREDENTIAL']
TRIAL_ACTIONS = _values['TRIAL_ACTIONS']
TRIAL_NORMALIZED_ACTIONS = _values['TRIAL_NORMALIZED_ACTIONS']
UNIVERSE = _values['UNIVERSE']
FEED = MappingProxyType(_values['feed'])
