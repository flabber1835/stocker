"""Exact admitted OWN627 identity and one pre-transaction closing session."""
from copy import deepcopy
import csv
import gzip
import io
import json
from pathlib import Path
import zipfile

from p01_native_resume_parent import check_spec,need,sha,digest,OUTER,INPUT

HERE=Path(__file__).parent
SPEC='p01_native_resume_predecessor.json'
END='2020-06-30';MAXIMUM=1;FIRST=(END,)
SOURCE='369995575874917058'
IAC='984687283821901795'
NATIVE_SHA='69e74a01139f387bb80ff07317d847a831e8f0e235c147524b918d1b1b975847'
CLOCK_SHA='b8c1a17f34fc094a8d1c3adf1b3c0de29ac956dbb4dc44caaf72842c8d463813'


def specification():
    value=json.loads((HERE/SPEC).read_bytes());check_spec(value)
    clock=value['source_clock_qualification']
    need(clock['extraction_sha256']==CLOCK_SHA and clock['hash_domain']=='EXTRACTION_NOT_UNAVAILABLE_RAW_HTML'
         and clock['raw_html_sha256'] is None and clock['exact_merger_minute_claimed'] is False
         and clock['scope']=='JUNE30_CLOSING_UNITS_ONLY_NO_JULY1_IDENTITY_OR_LEGAL_CONSIDERATION_ADMISSION',
         'EXACT_ONE_DAY_PRIMARY_CLOCK_SCOPE')
    need(value['native_scope_pins']['mtch2_native_term_sha256']==NATIVE_SHA,'EXACT_EXISTING_NATIVE_PROXY_PREIMAGE')
    return value


def reused_qualification(old,source_map):
    """Authenticate old proof metadata; never execute its old synthetic books."""
    spec=specification();descriptor=spec['reused_action_component'];path=Path(old)/descriptor['member']
    raw=path.read_bytes()
    need(len(raw)==descriptor['bytes'] and sha(raw)==descriptor['sha256'],'EXACT_REUSED_ADMITTED_ACTION_COMPONENT')
    value=json.loads(gzip.decompress(raw))
    flags=('target_independence_qualified','held_target_holding_qualified','ordinary_representation_qualified')
    need(all(value[k] is True for k in flags)
         and value['held_source_with_target_pending_qualified'] is False
         and value['financial_authority'] is False and value['qualification_state_adopted'] is False
         and value['source_map_identity_sha256']==descriptor['source_map_identity_sha256']==digest(source_map)
         and all(source_map['successor_all_sources'].get(n)==h for n,h in value['source_files'].items()),
         'REUSED_EXACT_CURRENT516_CANONICAL_COMPONENT_SCOPE')
    return dict(**{k:True for k in flags},held_source_with_target_pending_qualified=False,
        component_sha256=descriptor['sha256'],root_review_sha256=descriptor['root_review_sha256'],
        source_map_identity_sha256=digest(source_map),old_synthetic_components_reexecuted=False)


def source_rows(archive=Path('/frozen/archive/corpus.zip')):
    """Host input text only; public pins carry hashes, never market preimages."""
    from full_system_core import hosted
    hosted();spec=specification();member='observations-2020.csv.gz';expected=spec['frozen_observation_members'][member]
    wanted=spec['native_scope_pins']['raw_observation_rows'];found={}
    with zipfile.ZipFile(archive) as z:
        info=z.getinfo(member);import hashlib
        h=hashlib.sha256()
        with z.open(member) as stream:
            for chunk in iter(lambda:stream.read(1024**2),b''):h.update(chunk)
        need(info.file_size==expected['bytes'] and h.hexdigest()==expected['sha256'],'EXACT_RETAINED2020_INPUT_MEMBER')
        with z.open(member) as compressed,gzip.GzipFile(fileobj=compressed) as raw,io.TextIOWrapper(raw,encoding='utf8',newline='') as text:
            for row in csv.DictReader(text):
                if row['session']!=END:continue
                key=row['session']+'/'+row['security_id']
                if key in wanted:
                    need(key not in found and digest(row)==wanted[key],'EXACT_UNIQUE_PRE_EVENT_SOURCE_ROW')
                    found[key]=deepcopy(row)
    need(set(found)==set(wanted),'ALL_PRE_EVENT_SOURCE_ROWS_PRESENT')
    return found
