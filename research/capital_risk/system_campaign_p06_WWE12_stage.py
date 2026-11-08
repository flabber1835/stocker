"""Scoped exact P06 financial source-loader dispatch in the launcher."""
import json
from pathlib import Path
import system_campaign_p06_WWE12_runtime as runtime
from system_campaign_financial_partial import root_spec

def bind_launch(original,module):
    def launch(args):
        request=json.loads(args.request.read_bytes());spec=root_spec(args.arm)
        if not runtime.candidate(spec) or request.get('execution_mode')!=runtime.MODE:return original(args)
        runtime.request_financial(request,spec)
        import system_campaign_financial_review_repair as legacy_repair
        saved=legacy_repair.applies
        legacy_repair.applies=lambda value:False if runtime.candidate(value) else saved(value)
        try:
            with runtime.loader.context(spec,request,mode='launch',profile_validator=runtime.request_financial):
                return original(args)
        finally:legacy_repair.applies=saved
    return launch

def source_names():return (Path(__file__).name,*runtime.source_names())
