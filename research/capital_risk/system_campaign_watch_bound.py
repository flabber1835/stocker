"""An opt-in own-preimage check; the existing watch comparator stays strict."""
from copy import deepcopy
import hashlib,json
from full_system_benchmark import need
from system_campaign_compare import watch,facts


def bound_watch(left,right,left_preimage,right_preimage):
    need(len(left)==len(right),'BOUND_WATCH_SAME_COUNT')
    normalized=[deepcopy(left),deepcopy(right)]
    for index,(a,b) in enumerate(zip(left,right)):
        if a==b:continue
        need(a.get('schema')==b.get('schema')=='research.pooled-action-successor/1',
             'BOUND_WATCH_ORDINARY_INPUT_SUCCESSOR')
        preimages=[]
        for row,lookup in ((a,left_preimage),(b,right_preimage)):
            cp,raw=lookup(row)
            need(hashlib.sha256(raw).hexdigest()==row['overlay']['sha256'],
                 'BOUND_WATCH_ACTUAL_ARCHIVED_DOCUMENT')
            document=json.loads(raw)
            need(cp['run']['checkpoint_sha256']==row['predecessor_checkpoint_sha256']
                 and cp['run']['state_sha256']==row['state_sha256']
                 and cp['run']['input_sha256']==row['predecessor_input_sha256']
                 and cp['source_cursor']==row['unchanged_through'],
                 'BOUND_WATCH_ACTUAL_OWN_PREDECESSOR_INPUT')
            need(document['predecessor_checkpoint_sha256']==cp['run']['checkpoint_sha256'],
                 'BOUND_WATCH_ACTUAL_OWN_FACT_PREDECESSOR')
            preimages.append((cp,document))
        need(preimages[0][0]['base']==preimages[1][0]['base'],'BOUND_WATCH_IDENTICAL_BASE')
        facts(preimages[0][1],preimages[1][1])
        for rows in normalized:rows[index].pop('predecessor_input_sha256')
    watch(*normalized)
