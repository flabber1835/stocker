"""Source-only disjoint CELG component renderer; no execution or state bridge."""
import ast
import hashlib
import json
from pathlib import Path

CORE='shared/stock_strategy_shared/wealth_core/'
PAYLOAD=CORE+'merger_rights.py'
HERE=Path(__file__).parent
PHYSICAL_SHA='ace9da1520e6f540722237b12b4b378e0ff19caced1f03e8c4ad9fffa2ba1a59'
FINANCIAL_SHA='e6549198fb54b2da989af88ac30cb3ea381052318a10c4c993cd4343382d5fb3'
SOURCE_BINDING_SHA='cbff432d861381735e7bba6ecd79491b059405cde8840cc2d128dbbad85d0b14'
EXPECTED={
    CORE+'ledger.py':'c37a8656cc43a4807bf16e2fc6dcb97758cbe7271fc8d9a736ee526c9a9281f3',
    CORE+'terminal.py':'d145eb0787c58e092618d1b05f5f2d988449351ac146a050debd9e0cec1c44e6',
    'sentinel/controller/terminal_returns.py':'172c55b738753bcc9bcf29cf6ab3618d9de42d6f63f7e555d606508f7f740867',
}
ENUM_SITE=b'    TERMINAL_LIQUIDATION = "TERMINAL_LIQUIDATION"'
ENUM_INSERT=b'    MERGER_RIGHT_RECEIPT = "MERGER_RIGHT_RECEIPT"\n    MERGER_RIGHT_LIQUIDATION = "MERGER_RIGHT_LIQUIDATION"\n'
TAILS={CORE+'ledger.py':b'\nfrom .merger_rights import install_ledger as _install_merger_right_ledger\n_install_merger_right_ledger(globals())\n',
    CORE+'terminal.py':b'\nfrom .merger_rights import install_terminal as _install_merger_right_terminal\n_install_merger_right_terminal(globals())\n',
    'sentinel/controller/terminal_returns.py':b'\nfrom stock_strategy_shared.wealth_core.merger_rights import install_leadership as _install_merger_right_leadership\n_install_merger_right_leadership(globals())\n'}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def need(value,code):
    if not value:raise ValueError('REFUSED_CELG_SOURCE_'+code)

def render_modules(files):
    """Pure byte/AST transform; original functions are retained as exact prefix."""
    out=dict(files)
    for name,expected in EXPECTED.items():
        need(name in files and sha(files[name])==expected,'EXACT_OLD_CANONICAL_MODULE:'+name)
    payload=(HERE/'p01_celg_component.py').read_bytes();ast.parse(payload)
    out[PAYLOAD]=payload
    name=CORE+'ledger.py';raw=files[name]
    need(raw.count(ENUM_SITE)==1,'ONE_EXACT_ENUM_ADDITION_SITE')
    out[name]=raw.replace(ENUM_SITE,ENUM_INSERT+ENUM_SITE)+TAILS[name]
    for name in (CORE+'terminal.py','sentinel/controller/terminal_returns.py'):out[name]=files[name]+TAILS[name]
    for name in (*EXPECTED,PAYLOAD):ast.parse(out[name],filename=name)
    return out

def verify_rendered_modules(files):
    """Recover/check original bytes before importing any successor module."""
    originals={}
    for name,tail in TAILS.items():
        need(files[name].endswith(tail),'EXACT_DECLARED_INSTALL_TAIL:'+name)
        raw=files[name][:-len(tail)]
        if name==CORE+'ledger.py':
            need(raw.count(ENUM_INSERT)==1,'EXACT_TWO_NEW_ENUM_ROWS')
            raw=raw.replace(ENUM_INSERT,b'')
        need(sha(raw)==EXPECTED[name],'ORIGINAL_MODULE_BYTES_RECOVERED_EXACTLY:'+name)
        originals[name]=raw
    expected=render_modules(originals)
    need(all(files[n]==v for n,v in expected.items()),'EXACT_SOURCE_RENDERER_OUTPUT_NOT_ARBITRARY_ALLOWED_FILE_EDITS')
    return True

def render(files,expected_sources,*,financial_sources=None):
    need(len(files)==len(expected_sources)==515 and digest(expected_sources)==PHYSICAL_SHA
         and {n:sha(v) for n,v in files.items()}==expected_sources,
         'ALL515_ORIGINAL_SOURCE_BYTES_REQUIRED')
    if financial_sources is None:
        financial_sources=json.loads((HERE/'p01_action_clock_predecessor.json').read_bytes())['base']['sources']
    need(len(financial_sources)==223 and digest(financial_sources)==FINANCIAL_SHA
         and all(expected_sources.get(n)==v for n,v in financial_sources.items()),
         'EXACT_OWN_P01_223_CANONICAL_FINANCIAL_SOURCE_SUBSET')
    out=render_modules(files)
    changed={n for n in set(files)|set(out) if files.get(n)!=out.get(n)}
    need(changed==set(EXPECTED)|{PAYLOAD} and len(out)==516,'ONLY_DECLARED_CANONICAL_CAPABILITY_SOURCE_DELTA')
    manifest=dict(schema='research.p01-celg-component-source-successor/1',
        predecessor_all_sources=dict(expected_sources),successor_all_sources={n:sha(v) for n,v in out.items()},
        predecessor_financial_sources=dict(financial_sources),
        successor_financial_sources={**financial_sources,**{n:sha(out[n]) for n in changed}},
        original_source_binding_sha256=SOURCE_BINDING_SHA,
        changed={n:dict(before=expected_sources.get(n),after=sha(out[n])) for n in sorted(changed)},
        execution_scope='HOSTED_SYNTHETIC_COMPONENT_QUALIFICATION_ONLY',
        source_bridge_implemented=False,financial_predecessor_selected=False,financial_clock_admitted=False,
        original_native_nov20_action_removed=False,nov21_quote_backdated=False,
        financial_input_admitted=False,production_contacted=False)
    return out,manifest

def write_disjoint(files,expected_sources,destination):
    """Export source text only; refuses existing trees and every actual book."""
    out,manifest=render(files,expected_sources);destination=Path(destination)
    need(not destination.exists(),'NEW_DISJOINT_SOURCE_DESTINATION_REQUIRED')
    need(not any(n.startswith(('book/','lineage/')) for n in out),'SOURCE_EXPORT_CANNOT_INCLUDE_BOOK_STATE')
    destination.mkdir(parents=True)
    for name,raw in out.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return manifest
