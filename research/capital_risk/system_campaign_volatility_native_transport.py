"""Derive input retention from the exact existing private signal factory."""
import ast,hashlib,json
from pathlib import Path
from full_system_benchmark import need

FACTORY='sentinel/core/window_material.py'


def native_material(raw,*,expected_sha256,expected_horizon):
    need(hashlib.sha256(raw).hexdigest()==expected_sha256,'V_NATIVE_EXACT_PRIVATE_SIGNAL_FACTORY_BYTES')
    need(type(expected_horizon) is int and 1<=expected_horizon<=127,'V_NATIVE_ORIGINAL_FINITE_SIGNAL_HORIZON')
    cls,=[n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name=='Signal']
    fn,=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='from_feature']
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Assign) and len(n.targets)==1
           and ast.unparse(n.targets[0])=="value['closes']"]
    need(len(sites)==1,'V_NATIVE_ONE_ORIGINAL_SIGNAL_RETENTION_SITE')
    value=sites[0].value
    need(isinstance(value,ast.Subscript) and ast.unparse(value.value)=="value['closes']"
         and isinstance(value.slice,ast.Slice) and value.slice.upper is None and value.slice.step is None,
         'V_NATIVE_ORIGINAL_SIGNAL_TAIL_SLICE_ONLY')
    horizon=-ast.literal_eval(value.slice.lower)
    need(type(horizon) is int and horizon==expected_horizon,'V_NATIVE_FACTORY_AND_FROZEN_PARAMETER_HORIZON_EQUAL')
    return dict(signal_closes=horizon,factory_sha256=expected_sha256,financial_factory_modified=False)


def profile():
    root=Path('/out');binding=json.loads((root/'source-bindings.json').read_bytes())
    spec=json.loads((root/'spec.json').read_bytes());expected=spec['base']['sources'][FACTORY]
    need(binding['parameters']['family']=='V' and binding['all_sources'][FACTORY]==expected,
         'V_NATIVE_ORIGINAL_SOURCE_BINDING_AND_V_PROFILE')
    return native_material((Path('/variant')/FACTORY).read_bytes(),expected_sha256=expected,
                           expected_horizon=binding['parameters']['v_horizon'])
