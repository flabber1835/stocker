"""Explicit selected ordinary augmentation; historical sensor routes are retained."""
from contextlib import contextmanager
import json
from pathlib import Path

import system_campaign_ordinary_augmentation_data as data


def selected(spec):
    if not isinstance(spec,dict) or spec.get('arm') != 'P07':return False
    plan=data.catalog()
    root=spec.get('root_admission_sha256',spec.get('monthly_seed_root_admission_sha256'))
    return root == plan['parent_root_admission_sha256'] or (
        spec.get('retained_ordinary_augmentation_sha256') == data.sha((data.HERE/data.CATALOG).read_bytes()))


def source_names():
    return ('system_campaign_ordinary_augmentation_data.py','system_campaign_ordinary_augmentation_runtime.py',
        'system_campaign_ordinary_augmentation_router.py','system_campaign_ordinary_augmentation_cash_v1.py',
        data.CATALOG,'system_campaign_qualified_own_cash_literals.py',
        'system-campaign-p07-own1196-gbt-original-cash-literal.json',
        'system-campaign-p07-own1196-trq-original-cash-literal.json')


def declaration(spec):
    data.need(selected(spec),'AUGMENTATION_EXPLICIT_SELECTED_REQUEST_DECLARATION')
    plan=data.catalog()
    return dict(schema=data.SCHEMA,catalog_file=data.CATALOG,
        catalog_sha256=data.sha((data.HERE/data.CATALOG).read_bytes()),
        origin_root_admission_sha256=plan['parent_root_admission_sha256'],
        current_root_admission_sha256=spec['root_admission_sha256'],
        adoption_required=spec['root_admission_sha256']==plan['parent_root_admission_sha256'],
        original_model_inputs_and_certificates_preserved=True,canonical_financial_source_changed=False)


def unchanged_phase(spec):
    if selected(spec) and declaration(spec)['adoption_required']:return False
    return data.original.unchanged_phase(spec)


def implementation(root,cp,spec):
    if selected(spec):
        from system_campaign_ordinary_augmentation_runtime import api
        return api(root,cp,spec)
    import system_campaign_financial_additional_sensor_runtime as original
    return original


def preserve(root,cp,out,spec):
    return implementation(root,cp,spec).preserve(root,cp,out,spec)


def retained_models(root,cp,spec):
    return implementation(root,cp,spec).retained_models(root,cp,spec)


@contextmanager
def original_chain(root,cp,spec):
    with implementation(root,cp,spec).original_chain(root,cp,spec) as value:yield value


def run(cp,out,args,rows,observer,execution,spec,old):
    return implementation(old,cp,spec).run(cp,out,args,rows,observer,execution,spec,old)


def review(parent,evidence,out,spec,old):
    if selected(spec):return implementation(evidence,parent,spec).review(parent,evidence,out,spec,old)
    from system_campaign_financial_additional_sensor_review import review as original
    return original(parent,evidence,out,spec,old)


def review_driver(evidence,out,spec):
    if selected(spec):
        # Read-only DATA selection here; the actual canonical reader runs inside api.
        import gzip
        cp=json.loads(gzip.decompress((Path(evidence)/'book/checkpoint.json.gz').read_bytes()))
        return implementation(evidence,cp,spec).review_driver(evidence,out,spec)
    import system_campaign_financial_additional_sensor_runtime as original
    return original.review_driver(evidence,out,spec)
