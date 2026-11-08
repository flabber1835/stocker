"""Actual whole13 history must keep its original compiler byte identity."""
import gzip,importlib.util,json,sys
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
import system_campaign_source_exit_history as history
import system_campaign_source_exit_api as api
import system_campaign_source_exit_input_v1 as retained
from system_campaign_facts import sha,digest
from system_campaign_financial_partial import root_spec


def test_historical_API_keeps_exact_original_compiler_after_new_version_added():
 assert history.source is api.source is retained
 assert sha(Path(retained.__file__).read_bytes())=='d8b80226163b399251953d09c6877e1ef29b17bdf06a73530705ac72e60c9594'


def test_actual_saved_full13_history_uses_original_compiler_without_projection():
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
 F=R/'financial366-source-snapshot/authenticated-artifact-13587599730'
 helper=Path('C:/GitHub/stocker/.codex-tmp/p06-fin366-DATA-20261107/p06_FIN366_components_DATA.py')
 if not F.exists() or not helper.exists():pytest.skip('genuine authenticated FIN366 and qualified DATA helper required')
 mf=json.loads((F/'authenticated-manifest.json').read_bytes())['members'];root=Path('\\\\?\\'+str((F/'verified-output').resolve()))
 def member(name):
  raw=(root/name).read_bytes();assert dict(bytes=len(raw),sha256=sha(raw))==mf[name];return raw
 spec=importlib.util.spec_from_file_location('qualified_complete_parent_history_DATA',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 sys.path.insert(0,'C:/GitHub/stocker/.codex-tmp/p01-progress')
 import review_progress
 current=review_progress.checkpoint(member('book/checkpoint.json.gz'));before=digest(current)
 baseline=root_spec('P06','ed91d2845587672a335b6af5a921c96668432a6129d337db062c3eedff88c845')
 result=history.history(root,current,baseline,member=member,previous_history=lambda root,cp:m.previous_history(root,cp,member,review_progress.checkpoint),input_hash=lambda base,repairs:digest(dict(base=base,repairs=repairs)))
 assert result['full_inputs']==13 and result['new_input_adopted'] is True and digest(current)==before
