"""Read-only capture of the actual causal residual-peer breadth inputs."""
import gzip,hashlib,json,math,os,struct
from dataclasses import asdict
from pathlib import Path
from full_system_benchmark import need

def plain(value):
    if type(value) is float and not math.isfinite(value):return {'ieee754_binary64':struct.pack('>d',value).hex()}
    if value is None or type(value) in (str,int,float,bool):return value
    if isinstance(value,dict):return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [plain(v) for v in value]
    if hasattr(value,'item'):return plain(value.item())
    raise ValueError('REFUSED_CORRELATION_CAPTURE_TYPE')
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

class Observation:
    def __init__(self,path):self.path=Path(path);self.pending=None;self.rows=0;self.chain=digest('system-optimization-002/raw-correlation/1')
    def __enter__(self):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir(),'HOSTED_CORRELATION_CAPTURE_ONLY')
        from sentinel.controller import median5_breadth as module
        from research.pooled_vacancy_funding import runtime
        self.module,self.runtime=module,runtime;self.breadth,self.advance=module.breadth,runtime.advance
        self.stream=gzip.open(self.path,'xb',compresslevel=1)
        def breadth(state,feed,spy_history,peer_keys):
            need(self.pending is None,'ONE_BREADTH_PER_TRANSITION')
            result=self.breadth(state,feed,spy_history,peer_keys);held=[]
            for slot in sorted(state.episodes):
                ep=state.episodes[slot];series=feed.series.get(ep.security_id)
                held.append({'slot':slot,'security_id':ep.security_id,'peer_key':list(peer_keys[ep.security_id]),
                    'session_indices':list(series.session_indices) if series else [],
                    'signal_closes':list(series.signal_closes) if series else [],
                    'canonical_holding':asdict(result[1][len(held)])})
            self.pending=plain({'index':feed._session_index,'spy_history':list(spy_history),'held':held,'canonical_breadth':asdict(result[0])})
            return result
        def advance(run,published):
            need(self.pending is None,'NO_UNCOMMITTED_BREADTH_CAPTURE')
            result=self.advance(run,published)
            need(self.pending is not None,'ACTUAL_BREADTH_CALL_REQUIRED')
            material={'schema':'research.system-campaign-correlation-input/1','session':published.session,
                'publication_version':published.data_version,'input_sha256':run.input_sha256,
                'prior_state_sha256':run.state.state_hash,'next_state_sha256':result.state.state_hash,'material':self.pending}
            self.chain=digest({'previous':self.chain,'record':material});material['chain_sha256']=self.chain
            raw=json.dumps(material,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
            self.stream.write(raw);self.stream.flush();os.fsync(self.stream.fileno());self.rows+=1;self.pending=None
            return result
        module.breadth=breadth;runtime.advance=advance;return self
    def __exit__(self,*args):
        self.module.breadth=self.breadth;self.runtime.advance=self.advance;self.stream.close()
    def proof(self):return {'schema':'research.system-campaign-correlation-capture/1','rows':self.rows,'chain_sha256':self.chain,
        'pending_uncommitted':self.pending is not None,'financial_state_changed':False,'canonical_breadth_returned_unchanged':True}
