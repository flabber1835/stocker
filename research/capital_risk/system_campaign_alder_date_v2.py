"""Correct Packet.day dispatch; preserve the published v1 factual catalog."""
from dataclasses import asdict,replace
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import digest,sha
from system_campaign_alder_facts import AlderFacts


class AlderDateV2(AlderFacts):
    def __init__(self,path):
        super().__init__(path);self.compiler_sha=sha(Path(__file__).read_bytes())

    def __enter__(self):
        need(self.native is not None and self.hydrated_sha is not None,'ALDER_HYDRATED_BEFORE_WRAPPER')
        from research.pooled_vacancy_funding import backtest
        self.original=backtest.apply_repair
        def corrected(packet,loaded):
            changed=self.original(packet,loaded)
            if packet.day!=self.catalog['effective_session']:return changed
            need(digest(asdict(self.native))==self.catalog['native_term_sha256'] and self.native.cash_per_share is None
                 and not self.native.completeness(0)[0],'ALDER_UNRESOLVED_TERM_NOT_COMPLETED')
            need(not any(v.security_id==self.catalog['security_id'] for v in changed.terminal),'ALDER_NO_DUPLICATE_TERMINAL')
            return replace(changed,terminal=(*changed.terminal,replace(self.native,session=packet.day)))
        backtest.apply_repair=corrected;return self
