"""Independent expansion of the reviewed wire format for mutation fixtures."""
import json

from scripts.sentinel_source_history import encoded as encoded_profile
from sentinel import url_selected_source_basis as basis

__all__ = ['encoded_profile', 'expanded_profile']


def expanded_profile():
    value = json.loads(basis.PROFILE.read_bytes())
    anchor = value['candidate_files']
    records = {}
    for revision, record in value['retained_predecessors'].items():
        files = dict(anchor)
        for name in record['removed']:
            del files[name]
        files.update(record['overrides'])
        records[revision] = dict(source_sha256=record['source_sha256'], files=files)
    return {**value, 'retained_predecessors': records}
