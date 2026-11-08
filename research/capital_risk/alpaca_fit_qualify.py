"""Hosted component checks for the registered private leaf compiler."""
from datetime import date,timedelta
from types import SimpleNamespace
from alpaca_fit_inputs import hosted,need


def qualify(leaves,registered):
    hosted();rows=[]
    for profile in registered:
        module=leaves[profile.id];state=module.fresh();serial=0
        def advance(**overrides):
            nonlocal serial,state
            serial+=1
            values={'session':(date(2024,1,1)+timedelta(days=serial)).isoformat(),'shadow_drawdown':-.10,
                'damaged_breadth':float(profile.entry_damage),'green_breadth':.20,'shadow_r20':-.01}
            values.update(overrides)
            state,evidence=module.step(observation=SimpleNamespace(**values),base_target=1.,state=state)
            return evidence
        for i in range(profile.entry_sessions):
            evidence=advance();need(state['active']==(i==profile.entry_sessions-1),'REGISTERED_ENTRY_COUNTER')
        need(evidence['target']==float(profile.active_ceiling),'REGISTERED_ACTIVE_CEILING')
        advance(shadow_r20=None,damaged_breadth=None,green_breadth=None)
        need(state['active'] and state['recovery_streak']==0,'UNKNOWN_MUST_PRESERVE_ACTIVE')
        for i in range(profile.recovery_sessions):
            evidence=advance(shadow_drawdown=0.,damaged_breadth=.63,green_breadth=.20,shadow_r20=.01)
            need(state['active']==(i<profile.recovery_sessions-1),'REGISTERED_RECOVERY_COUNTER')
        need(evidence['target']==1.,'REGISTERED_RECOVERY_TARGET')
        rows.append({'profile_id':profile.id,'entry_confirmations':profile.entry_sessions,
            'recovery_confirmations':profile.recovery_sessions,'unknown_active_preserved':True,
            'canonical_leaf_component_cases':serial,'status':'COMPONENT_PASSED_NOT_ECONOMIC_RESULT'})
    return {'schema':'research.alpaca-fit-leaf-qualification/1','registered_count':len(rows),
        'profiles':rows,'financial_replay_qualified':False,'baseline_actual_path_equality_still_required':True}
