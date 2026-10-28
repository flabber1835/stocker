"""Isolated canonical Owned55 source variant, constructed only on hosted compute."""
from pathlib import Path
from types import ModuleType,SimpleNamespace
import hashlib,sys
from trace_screen import require,digest

RULE=dict(schema=1,entry_drawdown=-.10,entry_damage=.88,entry_green=.20,
    entry_sessions=5,recovery_damage=.63,recovery_green=.20,
    recovery_sessions=8,recovery_core_r20_above=0.,active_ceiling=.55)


def variant_source(raw,expected_sha):
    require(hashlib.sha256(raw).hexdigest()==expected_sha,'REFUSED_ENTRY_SOURCE_BYTES')
    before=b'entry_damage=.88';after=b'entry_damage=.75'
    require(raw.count(before)==1 and after not in raw,'REFUSED_ENTRY_SOURCE_BOUNDARY')
    changed=raw.replace(before,after,1)
    require(changed.replace(after,before,1)==raw,'REFUSED_ENTRY_SOURCE_REVERSE')
    return changed


def load_variants(expected_sha):
    from sentinel.controller import owned_impairment as baseline
    raw=Path(baseline.__file__).read_bytes()
    changed=variant_source(raw,expected_sha)
    require(baseline.RULE==RULE,'REFUSED_ENTRY_ORIGINAL_RULE')
    name='research_owned55_entry75_private'
    require(name not in sys.modules,'REFUSED_ENTRY_NAMESPACE_REUSE')
    candidate=ModuleType(name);candidate.__file__='/private/owned55-entry75.py'
    sys.modules[name]=candidate
    exec(compile(changed,candidate.__file__,'exec'),candidate.__dict__)
    require(candidate.RULE=={**RULE,'entry_damage':.75} and baseline.RULE==RULE,
        'REFUSED_ENTRY_RULE_ISOLATION')
    return baseline,candidate,dict(original_sha256=expected_sha,
        candidate_sha256=hashlib.sha256(changed).hexdigest(),
        changed_literal='entry_damage=.88 -> entry_damage=.75',only_declared_source_change=True,
        original_rule=baseline.RULE,candidate_rule=candidate.RULE)


class Policies:
    def __init__(self,baseline,candidate):
        self.modules=(baseline,candidate)
        self.states=[baseline.fresh(),candidate.fresh()]
        self.last_session=None

    def step(self,row):
        day=row['session'];before=digest(row);decision=row['decision']
        require(decision['session']==day and row['evidence']['observation']['session']==day,
            'REFUSED_ENTRY_OBSERVATION_CURSOR')
        require(self.last_session is None or self.last_session<day,'REFUSED_ENTRY_DUPLICATE')
        parent=decision['champion_target_core_exposure']
        evidence=[]
        for i,module in enumerate(self.modules):
            module.validate({'strategy':module.STRATEGY_ID},self.states[i],expected_session=self.last_session)
            state,audit=module.step(observation=SimpleNamespace(**row['evidence']['observation']),
                base_target=parent,state=self.states[i])
            require(module.validate({'strategy':module.STRATEGY_ID},state,expected_session=day).model_dump()==state,
                'REFUSED_ENTRY_POLICY_ROUNDTRIP')
            self.states[i]=state;evidence.append(audit)
        require(evidence[0]==decision['owned_impairment'] and
            evidence[0]['target']==decision['target_core_exposure'],'REFUSED_ENTRY_CONTROL_POLICY')
        require(0<=evidence[1]['target']<=evidence[0]['target']<=parent<=1,
            'REFUSED_ENTRY_CEILING_OR_PARENT')
        require(digest(row)==before,'REFUSED_ENTRY_INPUT_MUTATION')
        self.last_session=day
        return evidence

    def snapshot(self):
        return dict(last_session=self.last_session,control=self.states[0],candidate=self.states[1])

    def restore(self,value):
        require(set(value)=={'last_session','control','candidate'},'REFUSED_ENTRY_POLICY_SCHEMA')
        for module,state in zip(self.modules,[value['control'],value['candidate']]):
            require(module.validate({'strategy':module.STRATEGY_ID},state,
                expected_session=value['last_session']).model_dump()==state,'REFUSED_ENTRY_POLICY_STATE')
        self.states=[value['control'],value['candidate']];self.last_session=value['last_session']
