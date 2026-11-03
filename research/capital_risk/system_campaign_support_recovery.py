"""Recover absent proof sidecars only after byte-exact same-book admission."""
import os
from pathlib import Path
import shutil

from full_system_benchmark import need, save
from seal import sha256_file

SUPPORT = ('common-factual-and-uncertainty-basis.json',
           'uncertainty-certificate.jsonl', 'correlation-inputs.jsonl.gz')
BOOK = ('book/identity.json', 'book/checkpoint.json.gz', 'source-bindings.json',
        *(f'book/{n}.jsonl' for n in ('formation', 'daily', 'monthly', 'watch')))


def fingerprint(path):
    need(path.is_file() and not path.is_symlink(), 'SUPPORT_REGULAR_EXISTING_FILE')
    return dict(bytes=path.stat().st_size, sha256=sha256_file(path))


def recover_view(current, source, spec, support_spec, out):
    """Pure filesystem/hash checks; never execute or choose financial state."""
    current, source, out = map(Path, (current, source, out))
    need(current != source and not current.is_symlink() and not source.is_symlink(),
         'SUPPORT_DISTINCT_AUTHENTICATED_ROOTS')
    need(spec['arm'] == support_spec['arm'] == 'P02'
         and spec['selected_checkpoint'] == support_spec['selected_checkpoint'] == 'book/checkpoint.json.gz'
         and all(spec[k] == support_spec[k] for k in ('selected_session', 'outer_sha256',
             'inner_sha256', 'state_sha256', 'input_sha256', 'base', 'repairs', 'selected_file',
             'journals', 'source_binding_sha256')), 'SUPPORT_EXACT_SAME_SELECTED_BOOK')
    need(set(support_spec['support_files']) == set(SUPPORT), 'SUPPORT_COMPLETE_DECLARED_CLOSURE')
    bindings = {name: fingerprint(current/name) for name in BOOK}
    need(all(fingerprint(source/name) == value for name, value in bindings.items()),
         'SUPPORT_IDENTICAL_CHECKPOINT_IDENTITY_SOURCE_AND_FULL_JOURNALS')
    missing = [name for name in SUPPORT if not (current/name).exists()]
    need(missing and all(fingerprint(source/name) == support_spec['support_files'][name]
                         for name in missing), 'SUPPORT_EXACT_AUTHENTICATED_MISSING_FILES')
    need(not any(p.is_symlink() for p in current.rglob('*')), 'SUPPORT_NO_LINKED_EVIDENCE_PATH')
    view = current.parent/'admitted-proof-view'
    need(not view.exists(), 'SUPPORT_DISJOINT_NEW_VIEW')
    shutil.copytree(current, view, copy_function=os.link)
    preserved = out/'lineage/admitted-support';preserved.mkdir(parents=True)
    provenance = {}
    for name in SUPPORT:
        if name in missing:
            shutil.copyfile(source/name, view/name)
            shutil.copyfile(source/name, preserved/name)
        value = fingerprint(view/name)
        need(value == fingerprint(source/name) if name in missing else value == fingerprint(current/name),
             'SUPPORT_EXACT_VIEW_FILE_BYTES')
        provenance[name] = dict(**value, origin='AUTHENTICATED_SAME_BOOK_SUPPORT' if name in missing else 'CURRENT_BRANCH')
    need(all(fingerprint(view/name) == value for name, value in bindings.items()),
         'SUPPORT_VIEW_FINANCIAL_BYTES_UNCHANGED')
    save(preserved/'support-predecessor.json', support_spec)
    proof = dict(schema='research.same-book-support-recovery/1', current_run_id=spec['run_id'],
        current_artifact_id=spec['artifact_id'], current_zip_sha256=spec['zip_sha256'],
        support_run_id=support_spec['run_id'], support_artifact_id=support_spec['artifact_id'],
        support_zip_sha256=support_spec['zip_sha256'], selected_outer_sha256=spec['outer_sha256'],
        financial_files=bindings, files=provenance, original_branch_unchanged=True,
        all_full_journal_bytes_identical=True, no_financial_checkpoint_selected_from_support=True,
        financial_sessions_advanced=0, production_contacted=False)
    save(preserved/'recovery.json', proof)
    return view


def hosted_view(current, spec, support_spec, out, temp, key, *, limit):
    from probe import check_context
    from system_campaign_factual_admit import admit
    check_context(os.environ)
    if all((current/name).is_file() for name in SUPPORT):
        return current
    source = admit(support_spec, temp/'campaign-factual-transfer-p02-proof-support', key,
                   max_zip_bytes=limit)
    return recover_view(current, source, spec, support_spec, out)
