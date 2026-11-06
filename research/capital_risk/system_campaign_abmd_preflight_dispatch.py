"""Explicit readonly ABMD preparation after the unchanged legacy preflight."""
import gzip,json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_abmd_bounded_catalog import CASES
from system_campaign_abmd_bounded_sources import source_names as shared_source_names

HERE=Path(__file__).parent
CATALOGS={
 'P06':('P06-own1238-ABMD-bounded-catalog-v2.json','dc1f6fe12216fca27f79165a29a03b1b88c490344b727ea51f207e97970e1e90'),
 'P07':('P07-own1238-ABMD-bounded-catalog-v2.json','9ee81ba4dfe9ceb6e4d486be601e5e171126f949f4897cb605061aa7a5d5fdc1')}

def source_names():
    return (*shared_source_names(),Path(__file__).name,'P07-abmd-full24-source-plan.json')

def declaration(spec):
    arm=spec.get('arm')
    if arm not in CASES or spec.get('root_admission_sha256')!=CASES[arm]['root']:return None
    need(spec['financial_authority'] is False and spec['outer_sha256']==CASES[arm]['outer']
         and (spec['measured_closes'],spec['selected_session'],len(spec['repairs']))==
             (1238,'2022-11-30',CASES[arm]['inputs']),'ABMD_ENTRY_EXACT_CURRENT_FULL_OWN_ROOT')
    name,pin=CATALOGS[arm]
    return dict(catalog_file=name,catalog_sha256=pin,financial_sessions_advanced=0,checkpoint_adopted=False)

def preflight_entry(old,out,spec,legacy,*,old_bounded_enabled=False,abmd_declaration=None):
    from system_campaign_bounded_sensor_preparation import preflight_entry as previous
    need(type(old_bounded_enabled) is bool,'ABMD_ENTRY_EXPLICIT_OLD_PREPARATION_FLAG')
    previous(old,out,spec,legacy,enabled=old_bounded_enabled)
    if abmd_declaration is None:return
    from full_system_core import hosted
    hosted()
    need(abmd_declaration==declaration(spec) and abmd_declaration is not None,'ABMD_ENTRY_EXACT_SEPARATE_REQUEST_DECLARATION')
    from system_campaign_abmd_bounded_preparation import prepare
    cp=json.loads(gzip.decompress((Path(old)/spec['selected_checkpoint']).read_bytes()))
    return prepare(cp,out,spec,catalog_path=HERE/abmd_declaration['catalog_file'],
                   catalog_sha256=abmd_declaration['catalog_sha256'])
