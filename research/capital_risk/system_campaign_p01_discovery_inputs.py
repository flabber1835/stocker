"""Rehydrate only P01's own original ordinary and spin input contexts."""
from contextlib import contextmanager
import json
from pathlib import Path
from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_facts import FactualInputs,sha
from system_campaign_distribution_facts import DistributionFacts
from system_campaign_discovery_inputs import preserve_input_documents

@contextmanager
def retained_inputs(root,parent,out):
    hosted();root,out=Path(root),Path(out)
    preserve_input_documents(root,parent,out)
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json')
    v1.hydrate(out/'discovery-fnf-hydration.json')
    distribution=DistributionFacts('/driver/system-campaign-distribution-facts.json')
    distribution.hydrate(out/'discovery-distribution-hydration.json')
    for new,old in (('discovery-fnf-hydration.json','hydrated-factual-catalog.json'),
                    ('discovery-distribution-hydration.json','hydrated-distribution-catalog.json')):
        need((out/new).read_bytes()==(root/old).read_bytes(),'P01_EXACT_OWN_PRIOR_PRIVATE_INPUT_BYTES')
    need(all(json.loads((root/'book/repairs'/d['filename']).read_bytes())['schema']=='terminal-repair/1'
             for d in parent['repairs']),'P01_NO_P02_CONDITIONAL_MODELS_OR_OTHER_INPUT_ADOPTION')
    with v1,distribution:
        yield v1,distribution

def qualify_inputs(root,parent,out,objects,v1,distribution):
    hosted()
    from system_campaign_factual_run import qualify_inputs as qualify_original
    need(len(objects)==len(parent['repairs'])==8,'P01_ALL_EIGHT_ORIGINAL_INPUTS_LOADED')
    qualify_original(v1,objects[0],out/'original-fnf-packet-qualification.json')
    distribution.qualify(objects[-1],out/'original-distribution-packet-qualification.json')
