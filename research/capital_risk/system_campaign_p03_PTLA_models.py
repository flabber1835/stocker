"""The original B19, DOVA and STML loaders over the complete20/21 history."""
from contextlib import contextmanager
from pathlib import Path
from full_system_benchmark import need
import system_campaign_p03_PTLA_history as history
import system_campaign_bounded_sensor_runtime_v2 as dova
import system_campaign_p03_STML_source as stml


def hydrate_second(value,out):
 target=Path(out)/history.previous.SOURCE
 target.parent.mkdir(parents=True,exist_ok=True)
 return stml.hydrate(value,target)


@contextmanager
def codecs(root,current,spec,out,*,base_context):
 from full_system_core import hosted
 hosted();root,out=Path(root),Path(out);history.full(root,current)
 parent=current if len(current['repairs'])==20 else history.archived_parent(lambda n:(root/n).read_bytes())
 history.resources.parent_contract(parent,spec)
 from system_campaign_bounded_sensor_hydration import hydrate
 InputCodec=dova.InputCodec
 from system_campaign_bounded_sensor_lifecycle_data import evidence
 from system_campaign_second_bounded_codec import SuccessorCodec
 first,second=dova.catalog(),stml.catalog()
 with base_context(root,current,spec):
  native,_=hydrate(first,root/dova.SOURCE)
  with InputCodec(first['event'],evidence(first),native):
   native,_=hydrate_second(second,out)
   with SuccessorCodec(second['event'],stml.evidence(second),native,
     previous_event=first['event'],previous_evidence=evidence(first)) as codec:
    codec.previous_owner();yield codec


def installed():
 from full_system_core import hosted
 hosted()
 from research.pooled_vacancy_funding import backtest
 from system_campaign_second_bounded_codec import SuccessorCodec
 codec=getattr(backtest.load_repair,'__self__',None)
 need(type(codec)is SuccessorCodec and codec.event==stml.catalog()['event'] and backtest.load_repair==codec.load,
  'PTLA_MODELS_ACTUAL_INSTALLED_ORIGINAL_STML_SUCCESSOR')
 codec.previous_owner();return codec
