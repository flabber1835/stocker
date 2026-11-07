"""Complete interpretation-source commitments for one typed input generation."""
from pathlib import Path
from system_campaign_bounded_sensor_input import need,sha
from system_campaign_bounded_sensor_binding import INHERITED

FILES=frozenset(('system_campaign_bounded_sensor_input.py','system_campaign_bounded_sensor_binding.py',
    'system_campaign_bounded_sensor_catalog.py','system_campaign_bounded_sensor_models.py',
    'system_campaign_bounded_sensor_lifecycle_data.py','system_campaign_bounded_sensor_semantics.py'))

def verify(catalog,root=None):
    root=Path(__file__).parent if root is None else Path(root)
    pins=catalog.get('input_semantics_sources')
    need(type(pins) is dict and set(pins)==FILES|set(INHERITED), 'BOUNDED_SEMANTICS_COMPLETE_EXACT_SOURCE_SET')
    need(all(pins[name]==pin for name,pin in INHERITED.items()),'BOUNDED_SEMANTICS_IMMUTABLE_ORIGINAL_B19_CONTEXT_MATH')
    need(all(type(pin) is str and len(pin)==64 and sha((root/name).read_bytes())==pin for name,pin in pins.items()),
         'BOUNDED_SEMANTICS_ALL_ACTUAL_INTERPRETATION_SOURCE_BYTES')
    return True
