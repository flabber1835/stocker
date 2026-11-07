"""Whole original reporting proof from the exact admitted financial baseline."""
from types import FunctionType
from full_system_benchmark import need
import system_campaign_financial_partial as original
import system_campaign_source_exit_profiles as profiles
ROOT='ed91d2845587672a335b6af5a921c96668432a6129d337db062c3eedff88c845'

def reader(spec):
 original.validate_root_spec(spec)
 need(profiles.candidate(spec),'SOURCE_EXIT_REPORTING_EXACT_OWN_ADMITTED_BASELINE')
 profiles.profile(spec)
 def reporting_seed(requested):
  need(requested==spec,'SOURCE_EXIT_REPORTING_ONLY_EXACT_ACTUAL_BASELINE_SPEC')
  original.validate_root_spec(requested)
  return spec
 fn=original.monthly_reproduction
 need(fn.__closure__ is None,'SOURCE_EXIT_REPORTING_WHOLE_ORIGINAL_FUNCTION_WITHOUT_CLOSURE')
 result=FunctionType(fn.__code__,dict(fn.__globals__,reporting_seed=reporting_seed),fn.__name__,fn.__defaults__)
 result.__kwdefaults__=fn.__kwdefaults__
 need(result.__code__ is fn.__code__,'SOURCE_EXIT_REPORTING_IDENTICAL_COMPLETE_ORIGINAL_CODE')
 return result
