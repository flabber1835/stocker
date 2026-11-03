"""Prove index-to-config portability of the exact retained research image."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile

from seal import sha256_file

IDENTITY=json.loads(Path(__file__).with_name('runtime-identity.json').read_bytes())
EXECUTION_IMAGE=IDENTITY['config']


def require(value,code):
    if not value: raise ValueError(code)


def verify_archive(path: Path, identity: dict=IDENTITY) -> dict:
    require(path.stat().st_size==identity['archive_bytes'] and sha256_file(path)==identity['archive_sha256'],
            'REFUSED_RUNTIME_ARCHIVE_HASH')
    with tarfile.open(path,'r:') as tar:
        files={}
        for member in tar.getmembers():
            if member.isdir(): continue
            require(member.isfile() and member.name not in files,'REFUSED_RUNTIME_ARCHIVE_MEMBER')
            files[member.name]=member
            if member.name.startswith('blobs/sha256/'):
                with tar.extractfile(member) as stream:
                    digest=hashlib.file_digest(stream,'sha256').hexdigest()
                require(digest==member.name.rsplit('/',1)[-1],'REFUSED_RUNTIME_BLOB_HASH')

        def read(digest):
            name='blobs/sha256/'+digest.removeprefix('sha256:')
            require(name in files and files[name].size<2*1024**2,'REFUSED_RUNTIME_DESCRIPTOR')
            return json.loads(tar.extractfile(files[name]).read())

        top=json.loads(tar.extractfile('index.json').read())
        require([d['digest'] for d in top['manifests']]==[identity['original_index']],
                'REFUSED_ORIGINAL_RUNTIME_INDEX')
        index=read(identity['original_index'])
        selected=[d for d in index['manifests'] if d.get('platform')==dict(os='linux',architecture='amd64')]
        require(len(selected)==1 and selected[0]['digest']==identity['platform_manifest'],
                'REFUSED_RUNTIME_PLATFORM_MANIFEST')
        manifest=read(identity['platform_manifest'])
        require(manifest['config']['digest']==identity['config']
                and [d['digest'] for d in manifest['layers']]==identity['layer_blobs'],
                'REFUSED_RUNTIME_CONFIG_OR_LAYERS')
        for descriptor in [manifest['config'],*manifest['layers']]:
            name='blobs/sha256/'+descriptor['digest'].removeprefix('sha256:')
            require(name in files and files[name].size==descriptor['size'],'REFUSED_RUNTIME_LAYER_SIZE')
        config=read(identity['config'])
        require(config['rootfs']['diff_ids']==identity['diff_ids'] and config['os']=='linux'
                and config['architecture']=='amd64','REFUSED_RUNTIME_CONFIG_ROOTFS')
        legacy=json.loads(tar.extractfile('manifest.json').read())
        require(len(legacy)==1 and legacy[0]['Config']=='blobs/sha256/'+identity['config'].removeprefix('sha256:')
                and legacy[0]['Layers']==['blobs/sha256/'+d.removeprefix('sha256:') for d in identity['layer_blobs']],
                'REFUSED_RUNTIME_LEGACY_PROJECTION')
    return identity


def verify_loaded(image: dict, identity: dict=IDENTITY) -> None:
    require(image['Id']==identity['config'] and image['Os']=='linux' and image['Architecture']=='amd64'
            and image['RootFS']['Type']=='layers' and image['RootFS']['Layers']==identity['diff_ids'],
            'REFUSED_LOADED_RUNTIME_IDENTITY')
