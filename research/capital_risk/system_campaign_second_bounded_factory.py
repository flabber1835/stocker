"""One complete inherited certificate chain for successive bounded source events."""
import ast
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import system_campaign_bounded_sensor_binding as original
from system_campaign_bounded_sensor_input import require_no_position,need,sha
import system_campaign_financial_future as future
ORIGINAL_SHA='a9fcbe1d1c36069036dbddc1982f19c4092f32bc6007534cf4760da527af350d'
_TOKEN=object()
_METHODS=('__init__','values','recover','advance','witness')

def mark(cls,event,codec):
 cls._bounded_layer_token=_TOKEN
 cls._bounded_layer_event=deepcopy(event)
 cls._bounded_layer_codec=codec
 cls._bounded_layer_methods={name:(getattr(cls,name).__code__,getattr(cls,name).__closure__) for name in _METHODS}
 return cls

def parent_metadata(cls,event,codec):
 need(isinstance(cls,type) and cls.__dict__.get('_bounded_layer_token')is _TOKEN,
  'SECOND_FACTORY_ONLY_FRESH_QUALIFIED_ORIGINAL_PARENT_CLASS')
 previous=cls.__dict__['_bounded_layer_event']
 need(previous['effective_session']<event['native_session'] and previous['security_id']!=event['security_id']
  and codec.previous_owner()is cls.__dict__['_bounded_layer_codec'],
  'SECOND_FACTORY_ACTUAL_DECLARED_PREVIOUS_CODEC_AND_ORDERED_EVENT')
 need(all(getattr(cls,n).__code__ is code and getattr(cls,n).__closure__ is closure
  for n,(code,closure) in cls.__dict__['_bounded_layer_methods'].items()),
  'SECOND_FACTORY_COMPLETE_ORIGINAL_PARENT_METHOD_CODE_AND_CLOSURES')
 return previous

def factory_tree(raw):
 need(sha(raw)==ORIGINAL_SHA,'SECOND_FACTORY_EXACT_ORIGINAL_BINDING_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='certificate_class']
 cls,=[n for n in ast.walk(fn) if isinstance(n,ast.ClassDef) and n.name=='BoundedCertificate']
 need(len(cls.bases)==1 and ast.unparse(cls.bases[0])=='b.Certificate','SECOND_FACTORY_ONE_ORIGINAL_SUPERCLASS_SITE')
 cls.bases=[ast.Name(id='PreviousCertificate',ctx=ast.Load())]
 return ast.fix_missing_locations(fn)

def absence(prior,sid):
 require_no_position(prior,sid)
 future.require_source_scope(prior.wealth_core,prior.pending,prior.ledger,dict(security_id=sid))

def first_factory(event,source,codec,native,*,inherited_root):
 need(sha(Path(original.__file__).read_bytes())==ORIGINAL_SHA,'SECOND_FACTORY_UNCHANGED_FIRST_FACTORY_SOURCE')
 fn=original.certificate_class
 basis=FunctionType(original.basis.__code__,dict(original.basis.__globals__,require_no_position=absence),
  original.basis.__name__,original.basis.__defaults__)
 bound=FunctionType(fn.__code__,dict(fn.__globals__,require_no_position=absence,basis=basis),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__
 return mark(bound(event,source,codec,native,inherited_root=inherited_root),event,codec)

def second_factory(event,source,codec,native,*,inherited_root,previous_class):
 from full_system_core import hosted
 hosted()
 from system_campaign_financial_branches import Certificate
 from system_campaign_second_bounded_codec import SuccessorCodec
 need(type(codec)is SuccessorCodec and issubclass(previous_class,Certificate)
  and previous_class.append is Certificate.append,'SECOND_FACTORY_ONE_ORIGINAL_B19_APPEND_CHAIN')
 parent_metadata(previous_class,event,codec)
 # The original factory retains all imports, source checks and method bodies.
 basis=FunctionType(original.basis.__code__,dict(original.basis.__globals__,require_no_position=absence),
  original.basis.__name__,original.basis.__defaults__)
 namespace=dict(vars(original),PreviousCertificate=previous_class,require_no_position=absence,basis=basis)
 exec(compile(ast.Module(body=[factory_tree(Path(original.__file__).read_bytes())],type_ignores=[]),
  '<complete-original-bounded-factory-one-previous-class-binding>','exec'),namespace)
 return mark(namespace['certificate_class'](event,source,codec,native,inherited_root=inherited_root),event,codec)
