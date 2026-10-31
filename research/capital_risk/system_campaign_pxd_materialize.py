"""Materialize a schema-selected real descriptor without checkpoint projection."""
from contextlib import contextmanager
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_close_scope import SCHEMA as CLOSE
from system_campaign_pxd_scope import SCHEMA as PXD


def descriptor_for(root,checkpoint,schema):
    from system_campaign_pxd_basis import documents
    need(schema in (CLOSE,PXD),'PXD_MATERIALIZE_ONLY_DECLARED_GUARDED_SCHEMAS')
    matches=[d for d,v in documents(root,checkpoint) if v['schema']==schema]
    need(len(matches)==1,'PXD_MATERIALIZE_EXACTLY_ONE_SCHEMA_SELECTED_ACTUAL_DESCRIPTOR')
    return matches[0]


@contextmanager
def materialized(codec,root,descriptor,*,schema):
    need(schema in (CLOSE,PXD) and descriptor['filename']==descriptor['sha256']+'.json'
         and len(descriptor['sha256'])==64
         and all(v in '0123456789abcdef' for v in descriptor['sha256']),
         'PXD_MATERIALIZE_SAFE_EXACT_GUARDED_DESCRIPTOR')
    path=Path(root)/'book/repairs'/descriptor['filename'];raw=path.read_bytes()
    need(sha(raw)==descriptor['sha256'] and json.loads(raw)['schema']==schema,
         'PXD_MATERIALIZE_EXACT_SCHEMA_AND_INPUT_BYTES')
    with codec:
        obj=codec.load(path,resume_session=descriptor['resume_session'],
            predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'])
        need(obj.sha256==descriptor['sha256'] and len(codec.objects)==1 and codec.objects[0] is obj,
             'PXD_MATERIALIZE_ACTUAL_TYPED_LOADED_OBJECT_REQUIRED')
        yield codec
