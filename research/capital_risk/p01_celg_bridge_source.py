"""Pure source renderer for the separately qualified financial CELG capability."""
import ast
import re
from pathlib import Path

import p01_celg_source as component

HERE=Path(__file__).parent
PAYLOAD=component.PAYLOAD
METADATA=frozenset(('sentinel/economic-implementation-v2.json','sentinel/economic_manifest.py'))
CAPABILITY=frozenset(component.EXPECTED)|{PAYLOAD}
CHANGED=CAPABILITY|METADATA
FINANCIAL_CHANGED=CHANGED-{'sentinel/economic-implementation-v2.json'}
sha=component.sha
digest=component.digest
need=component.need
COMPONENT_PINS={'p01_celg_source.py':'191bc504c8002552e6c7e23a3add7644965ba48e98ae9b0fc9b93a7a733c45e2',
    'p01_celg_component.py':'16b47710afe779f2f4c2921c073a89bd6b3cac88107ce2b17c810745c8b1765b'}


def render(files,expected_sources,*,financial_sources=None):
    need(all(sha((HERE/n).read_bytes())==h for n,h in COMPONENT_PINS.items()),
         'EXACT_INDEPENDENTLY_QUALIFIED_COMPONENT_SOURCE_BYTES')
    out,prior=component.render(files,expected_sources,financial_sources=financial_sources)
    payload=(HERE/'p01_celg_bridge_payload.py').read_bytes();ast.parse(payload)
    need(b'CELG_SYNTHETIC_COMPONENT_QUALIFICATION' in payload
         and b'AUTHENTICATED_RETAINED_ALPACA_RAW_SIP_INPUT' in payload
         and b'2.30' not in payload and b'2.25' not in payload,
         'FINANCIAL_PAYLOAD_REQUIRES_ACTUAL_AUTHENTICATED_INPUT')
    out[PAYLOAD]=payload
    from core_manifest import extend
    out=extend(out)
    changed={n for n in set(files)|set(out) if files.get(n)!=out.get(n)}
    need(changed==CHANGED and len(out)==516,'THREE_INSTALL_SITES_NEW_MODULE_AND_TWO_EXPLICIT_IDENTITY_METADATA_PATHS')
    manifest=dict(schema='research.p01-celg-financial-source-successor-map/1',
        predecessor_all_sources=prior['predecessor_all_sources'],
        predecessor_economic_manifest=files['sentinel/economic-implementation-v2.json'].decode(),
        predecessor_economic_manifest_reader=files['sentinel/economic_manifest.py'].decode(),
        successor_all_sources={n:sha(v) for n,v in out.items()},
        predecessor_financial_sources=prior['predecessor_financial_sources'],
        successor_financial_sources={**prior['predecessor_financial_sources'],
                                    **{n:sha(out[n]) for n in FINANCIAL_CHANGED}},
        original_source_binding_sha256=component.SOURCE_BINDING_SHA,
        changed={n:dict(before=expected_sources.get(n),after=sha(out[n])) for n in sorted(CHANGED)},
        synthetic_component_successor_map_sha256='fb7ba21fc834d1a35edf050ab394487ac83fb7ab0d5f82d2ced327aff36ed836',
        synthetic_component_review_sha256='f4d2d0f39d16b1e73b9010d55ae6f19720777894233501d71c0ed03b4ea82d1a',
        execution_scope='HOSTED_OWN475_SOURCE_AND_INPUT_BRIDGE_QUALIFICATION_REQUIRED',
        financial_predecessor_admitted=False,production_contacted=False)
    return out,manifest


def verify_rendered_modules(files,source_map=None):
    originals={}
    for name,tail in component.TAILS.items():
        need(files[name].endswith(tail),'EXACT_FINANCIAL_INSTALL_TAIL')
        raw=files[name][:-len(tail)]
        if name==component.CORE+'ledger.py':
            need(raw.count(component.ENUM_INSERT)==1,'EXACT_TWO_RIGHT_ENUMS')
            raw=raw.replace(component.ENUM_INSERT,b'')
        need(sha(raw)==component.EXPECTED[name],'ALL_OLD_CANONICAL_FUNCTION_BYTES_EXACT')
        originals[name]=raw
    expected=component.render_modules(originals)
    expected[PAYLOAD]=(HERE/'p01_celg_bridge_payload.py').read_bytes()
    need(all(files[n]==v for n,v in expected.items()),'EXACT_FINANCIAL_CAPABILITY_RENDERER_OUTPUT')
    need(source_map is not None,'IDENTITY_METADATA_PREIMAGE_MAP_REQUIRED')
    from core_manifest import extend
    old_manifest=source_map['predecessor_economic_manifest']
    old_reader=source_map['predecessor_economic_manifest_reader']
    old_files={**files,**originals,
        'sentinel/economic-implementation-v2.json':old_manifest.encode(),
        'sentinel/economic_manifest.py':old_reader.encode()}
    old_files.pop(PAYLOAD)
    recreated,_=render(old_files,source_map['predecessor_all_sources'],
                       financial_sources=source_map['predecessor_financial_sources'])
    need(recreated==files,'EXACT_FULL_FINANCIAL_RENDER_AND_IDENTITY_METADATA_TRANSFORM')
    return True


def write_disjoint(files,expected_sources,destination,*,financial_sources=None):
    out,manifest=render(files,expected_sources,financial_sources=financial_sources)
    destination=Path(destination)
    need(not destination.exists() and not any(n.startswith(('book/','lineage/')) for n in out),
         'DISJOINT_SOURCE_ONLY_DESTINATION')
    destination.mkdir(parents=True)
    for name,raw in out.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return manifest
