"""Preserve the exact verified encrypted ancestor; never alter old evidence."""
import shutil
from pathlib import Path
from full_system_benchmark import need,save
from seal import sha256_file


def preserve(old,out,spec):
    source=old.parent/'predecessor.zip';target=out/'lineage/verified-ancestor.zip';target.parent.mkdir(parents=True,exist_ok=True)
    need(source.is_file() and source.stat().st_size==spec['zip_bytes']
         and sha256_file(source)==spec['zip_sha256'],'ANCESTOR_EXACT_VERIFIED_SOURCE_ZIP')
    shutil.copyfile(source,target)
    need(target.stat().st_size==spec['zip_bytes'] and sha256_file(target)==spec['zip_sha256'],
         'ANCESTOR_EXACT_PRESERVED_ZIP')
    proof={'schema':'research.system-campaign-encrypted-ancestor/1','artifact_id':spec['artifact_id'],
        'source_run_id':spec['run_id'],'source_head':spec['head'],'zip_bytes':spec['zip_bytes'],
        'zip_sha256':spec['zip_sha256'],'path':target.relative_to(out).as_posix(),
        'old_archive_and_plaintext_unchanged':True,'production_contacted':False}
    save(out/'lineage/ancestor.json',proof);return proof
