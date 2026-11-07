"""Actual admitted full11/173 metadata; no future checkpoint or runtime authority."""
from pathlib import Path
import json
import system_campaign_p06_WWE_admission as authority
import system_campaign_p06_WWE173_preconditions as preconditions
from system_campaign_bounded_sensor_input import need,sha,digest
ROOT='edfe96119e6f8bf833e54189452698bca2bfca65676e2d0a861bb6a9ea69bf0f'
OUTER=preconditions.OUTER
encoded=authority.encoded
def parent_contract(current,spec):return authority.parent(current,spec)
def metadata():return preconditions.fact()
def source_names():return (Path(__file__).name,*authority.source_names())
