"""Hosted review-only codec materialization; immutable financial outputs only."""
from pathlib import Path
from types import FunctionType

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import sha
import system_campaign_p02_close_run as original

SOURCES = {
    'system_campaign_p02_close_run.py': '1669a45a0010287289e0b0a59c7e85142e00aff50ec55d1ab4e03e63ff39c00c',
    'system_campaign_close_scope.py': '76c7229d84405053a8212111dedffe435da7a103a68974c4e2cf70655c0e7af8',
}


def codec_factory(base, root, checkpoint, report):
    descriptor = checkpoint['repairs'][-1]
    class Materialized(base):
        def __enter__(self):
            super().__enter__()
            try:
                obj = self.load(Path(root) / 'book/repairs' / descriptor['filename'],
                    resume_session=descriptor['resume_session'],
                    predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'])
                need(obj.sha256 == descriptor['sha256'] and self.objects == [obj],
                     'CLOSE_REVIEW_MATERIALIZED_EXACT_CANONICAL_DESCRIPTOR')
                report.update(input_sha256=obj.sha256,
                    resume_session=descriptor['resume_session'],
                    predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'],
                    actual_nested_canonical_repair_loaded=True)
                return self
            except BaseException:
                super().__exit__(None, None, None)
                raise
    return Materialized


def review(out, root, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    for name, expected in SOURCES.items():
        need(sha((Path(__file__).parent / name).read_bytes()) == expected
             and request['sources'][name] == expected,
             'CLOSE_REVIEW_MATERIALIZATION_UNCHANGED_PUBLISHED_BODY_AND_CODEC')
    checkpoint = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    report = dict(status='STOPPED_EVIDENCE_REVIEW_ONLY_MATERIALIZATION',
        checkpoint_sha256=checkpoint['sha256'], financial_sessions_advanced=0,
        canonical_financial_source_changed=False, input_bytes_changed=False,
        stopped_book_changed=False, production_contacted=False)
    factory = codec_factory(original.CloseCodec, root, checkpoint, report)
    fn = original.review
    need(fn.__closure__ is None, 'CLOSE_REVIEW_MATERIALIZATION_ORIGINAL_BODY_WITHOUT_CLOSURE')
    checked = FunctionType(fn.__code__, dict(fn.__globals__, CloseCodec=factory), fn.__name__, fn.__defaults__)
    checked.__kwdefaults__ = fn.__kwdefaults__
    checked(out, root, old, spec, request, timing)
    need(journal.read_checkpoint(root / 'book/checkpoint.json.gz') == checkpoint,
         'CLOSE_REVIEW_MATERIALIZATION_STOPPED_CHECKPOINT_UNCHANGED')
    save(out / 'close-review-materialization.json', report)
    return report
