"""Version selection and outer retention; immutable input generations coexist."""
from contextlib import contextmanager, ExitStack
import json
from pathlib import Path

from system_campaign_financial_compound_input_v2 import need,sha


def versions():
    import system_campaign_financial_compound_runtime as v1
    import system_campaign_financial_compound_runtime_v2 as v2
    import system_campaign_financial_distribution_standard_runtime as standard
    return (v1,v2,standard)


def selected(cp,arm):
    found=[v for v in versions() if v.applies(cp,arm)]
    need(len(found)<=1,'COMPOUND_VERSION_ONE_UNAMBIGUOUS_EXACT_INITIAL_PHASE')
    return found[0] if found else None


def retained_versions(root,cp):
    root=Path(root);modules=versions();found={m.CATALOG_REF:[] for m in modules}
    for d in cp['repairs']:
        raw=(root/'book/repairs'/d['filename']).read_bytes()
        need(sha(raw)==d['sha256'],'COMPOUND_VERSION_ALL_RETAINED_SOURCE_BYTES')
        for row in json.loads(raw).get('source_evidence',[]):
            if row['reference'] in found:found[row['reference']].append(d)
    need(all(len(v)<=1 for v in found.values()),'COMPOUND_VERSION_ONE_ACTIVATION_PER_GENERATION')
    descriptors=[v[0] for v in found.values() if v]
    phases=[(v['resume_session'],v['predecessor_checkpoint_sha256']) for v in descriptors]
    need(len(set(phases))==len(phases),'COMPOUND_VERSION_NO_AMBIGUOUS_SAME_PHASE_ADOPTION')
    return tuple(m for m in modules if found[m.CATALOG_REF])


@contextmanager
def retained_context(root,cp,out):
    # Both enter outside the preexisting B19/APHA stack. Each delegates foreign
    # parsed object types; neither hides Codec from APHA's immutable unwrap.
    retained_versions(root,cp)
    with ExitStack() as stack:
        for module in versions():stack.enter_context(module.retained_context(root,cp,out))
        yield


def review_retained(root,cp):
    for module in retained_versions(root,cp):
        if hasattr(module,'review_retained'):module.review_retained(root,cp)


@contextmanager
def initial_context(cp,out,spec,loaded):
    module=selected(cp,spec['arm'])
    need(module is not None,'COMPOUND_VERSION_INITIAL_REQUIRES_ONE_SELECTED_PHASE')
    if module.__name__.endswith('_v2'):
        from system_campaign_financial_resume import AdoptionGate
        with AdoptionGate(cp,Path(out)/'book',Path(out)/'input-adoption',loaded.sha256,loaded.earliest_affected_session):
            with module.initial_context(cp,out,spec,loaded),module.ordinary_events(out,cp):yield
    else:
        with module.initial_context(cp,out,spec,loaded):yield
