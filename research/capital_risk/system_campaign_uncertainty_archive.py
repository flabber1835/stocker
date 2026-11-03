"""Resolve one documented reader/producer archive-name mismatch, read only."""
import gzip
import json
from pathlib import Path
import shutil

from full_system_benchmark import need, save
from full_system_core import hosted
from system_campaign_facts import digest, sha
from system_campaign_uncertainty_review import review as strict_review

REQUESTED = 'book/pre-event/2019-10-22.json.gz'


class EvidenceRoot:
    """Only one logical path is resolved; no checkpoint alias is written."""
    def __init__(self, root, actual):
        self.root, self.actual = Path(root), Path(actual)

    def __truediv__(self, name):
        return self.actual if str(name) == REQUESTED else self.root / name


def resolve(root):
    root=Path(root)
    with (root/'uncertainty-certificate.jsonl').open('rb') as stream:
        first=json.loads(stream.readline())
    need(first['session']=='2019-10-22', 'UNCERTAINTY_ARCHIVE_EXACT_FIRST_EVENT')
    matches=[]
    for path in (root/'book/pre-event').glob('2019-10-22-*.json.gz'):
        raw=path.read_bytes();cp=json.loads(gzip.decompress(raw))
        need(cp['sha256']==digest({k:v for k,v in cp.items() if k!='sha256'})
             and path.name=='2019-10-22-'+cp['sha256']+'.json.gz',
             'UNCERTAINTY_ARCHIVE_CANONICAL_PRODUCER_NAME_AND_OUTER_DIGEST')
        if (cp['source_cursor']=='2019-10-21'
                and cp['run']['state_sha256']==first['prior_state_sha256']
                and cp['run']['input_sha256']==first['input_sha256']):
            matches.append((path,cp,sha(raw)))
    need(len(matches)==1, 'UNCERTAINTY_ARCHIVE_UNIQUE_EXACT_PRE_EVENT_STATE_AND_INPUT')
    path,cp,file_sha=matches[0]
    return path,dict(schema='research.uncertainty-readonly-archive-resolution/1',
        requested=REQUESTED,actual=path.relative_to(root).as_posix(),file_sha256=file_sha,
        outer_sha256=cp['sha256'],source_cursor=cp['source_cursor'],
        state_sha256=cp['run']['state_sha256'],input_sha256=cp['run']['input_sha256'],
        exact_first_certificate_identity=True,checkpoint_bytes_or_name_changed=False,
        new_checkpoint_or_alias_created=False,financial_sessions_advanced=0)


def review(root, output):
    hosted()
    cp=json.loads(gzip.decompress((root/'book/checkpoint.json.gz').read_bytes()))
    if cp['source_cursor']<'2019-10-22':
        return strict_review(root,output)
    actual,proof=resolve(root)
    strict_review(EvidenceRoot(root,actual),output)
    save(output.parent/'uncertainty-archive-resolution.json',proof)


def preserve(root, output):
    actual,proof=resolve(root)
    target=output/'book/pre-event'/actual.name
    target.parent.mkdir(parents=True,exist_ok=True)
    need(not target.exists(),'UNCERTAINTY_ARCHIVE_DISJOINT_NEW_EVIDENCE')
    shutil.copyfile(actual,target)
    need(sha(target.read_bytes())==proof['file_sha256'],'UNCERTAINTY_ARCHIVE_PRESERVED_EXACT_GZIP')
    save(output/'uncertainty-event-archive-preservation.json',dict(**proof,
        preserved_as=target.relative_to(output).as_posix(),same_name_and_bytes=True))
    return target
