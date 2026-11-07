"""Source-only resource closure, shared by continuation profiles."""
from collections.abc import Callable, Mapping, Sequence
from hashlib import sha256
from pathlib import PurePosixPath
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Requirement(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    path:str
    bytes:int=Field(gt=0)
    sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    role:Literal['historical_asset','pre_event_archive']

    @model_validator(mode='after')
    def safe_resource(self):
        p=PurePosixPath(self.path)
        if p.is_absolute() or p.as_posix()!=self.path or '..' in p.parts or '\\' in self.path or ':' in self.path:
            raise ValueError('DEPENDENCY_UNSAFE_RESOURCE_PATH')
        if self.role=='pre_event_archive':
            if not re.fullmatch(r'book/pre-event/\d{4}-\d{2}-\d{2}-[0-9a-f]{64}\.json\.gz',self.path):
                raise ValueError('DEPENDENCY_ONLY_ORIGINAL_PRE_EVENT_ARCHIVE')
        elif self.path.startswith(('book/','lineage/')) or self.path in ('request.json','spec.json','uncertainty-certificate.jsonl'):
            raise ValueError('DEPENDENCY_NO_CURRENT_BOOK_OR_CONTROL_ALIAS')
        return self

def pin(raw:bytes)->dict:
    return dict(bytes=len(raw),sha256=sha256(raw).hexdigest())

def build(declared:Mapping[str,dict],resolutions:Sequence[dict],read:Callable[[str],bytes])->dict:
    """Resolve every original proof reference; never parse or create a book."""
    required={n:Requirement(path=n,role='historical_asset',**p) for n,p in declared.items()}
    references=[]
    for resolution in resolutions:
        if set(resolution)!={'actual','gzip_sha256','outer_sha256','state_sha256','input_sha256'}:
            raise ValueError('DEPENDENCY_COMPLETE_ORIGINAL_EVENT_RESOLUTION_REQUIRED')
        name=resolution['actual']
        if not name.endswith('-'+resolution['outer_sha256']+'.json.gz'):
            raise ValueError('DEPENDENCY_ORIGINAL_PRODUCER_NAME_REQUIRED')
        raw=read(name);actual=pin(raw)
        if actual['sha256']!=resolution['gzip_sha256']:
            raise ValueError('DEPENDENCY_REFERENCED_ARCHIVE_BYTES_CHANGED')
        item=Requirement(path=name,role='pre_event_archive',**actual)
        if name in required and required[name]!=item:
            raise ValueError('DEPENDENCY_CONFLICTING_RESOURCE_REQUIREMENTS')
        required[name]=item;references.append(dict(resolution))
    for name,item in required.items():
        if pin(read(name))!={k:getattr(item,k) for k in ('bytes','sha256')}:
            raise ValueError('DEPENDENCY_SOURCE_RESOURCE_BYTES_CHANGED:'+name)
    return dict(schema='research.continuation-resource-dependency-closure/1',
        requirements=[required[n].model_dump() for n in sorted(required)],
        event_resolutions=sorted(references,key=lambda r:r['actual']),financial_authority=False,
        financial_checkpoint_replaced=False,financial_sessions_advanced=0)

def copy_checked(manifest:dict,read:Callable[[str],bytes],write:Callable[[str,bytes],None])->None:
    for value in manifest['requirements']:
        item=Requirement.model_validate(value);raw=read(item.path)
        if pin(raw)!={'bytes':item.bytes,'sha256':item.sha256}:
            raise ValueError('DEPENDENCY_SOURCE_CHANGED_DURING_COPY:'+item.path)
        write(item.path,raw)

def verify(manifest:dict,declared:Mapping[str,dict],resolutions:Sequence[dict],
           source:Callable[[str],bytes],destination:Callable[[str],bytes])->bool:
    if manifest!=build(declared,resolutions,source):
        raise ValueError('DEPENDENCY_MANIFEST_OMITS_OR_ALTERS_REQUIRED_RESOURCE')
    for value in manifest['requirements']:
        item=Requirement.model_validate(value)
        if pin(destination(item.path))!={'bytes':item.bytes,'sha256':item.sha256}:
            raise ValueError('DEPENDENCY_DESTINATION_MISSING_OR_CHANGED:'+item.path)
    return True
