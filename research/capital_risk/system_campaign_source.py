"""Campaign baseline compiler; storage cadence only beyond the qualified basis."""
import ast,hashlib
from pathlib import Path
from full_system_source import BASELINE,build as original_build,replace

def build(source,destination):
    binding=original_build(source,destination,BASELINE)
    name='research/pooled_vacancy_funding/backtest.py';path=Path(destination)/name;raw=path.read_bytes()
    text=replace(raw.decode(),
        '            if packet.day==START or packet.day==END or measurement[min(completed,len(measurement)-1)][:7]!=packet.day[:7]:\n                save()',
        '            if (packet.day==START or packet.day==END or axis[buffer.index+1][:7]!=packet.day[:7]\n'
        '                    or axis[buffer.index+1]==START):\n                save()')
    ast.parse(text,name);path.write_bytes(text.encode())
    sha=hashlib.sha256(path.read_bytes()).hexdigest();binding['all_sources'][name]=sha;binding['changed'][name]['after']=sha
    binding['schema']='research.system-campaign-baseline-source/1';binding['checkpoint_cadence']='ORIGIN_FORMATION_BOUNDARY_PRE_EVENT_MONTH_PAUSE_END'
    return binding
