"""Use unchanged canonical prefix verification with read-only handles."""
from pathlib import Path
from full_system_benchmark import need

def reader(original,root,streams):
    obj=original.__new__(original);obj.root=Path(root).resolve();obj._files={};obj._closed=False;obj._ready=False
    try:
        for name in streams:obj._files[name]=(obj.root/(name+'.jsonl')).open('rb')
    except BaseException:
        obj.close();raise
    return obj

def review(root,output):
    from research.pooled_vacancy_funding import journal
    from full_system_core import review as canonical_review
    original=journal.Journal
    def readonly(root,*,resume=False):
        need(resume,'READ_ONLY_REVIEW_CANNOT_CREATE_JOURNAL');return reader(original,root,journal.STREAMS)
    journal.Journal=readonly
    try:return canonical_review(root,output)
    finally:journal.Journal=original
