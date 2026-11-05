"""P10's own immutable diagnostic/source/input contract; no strategy imports."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

TAINT = 'DISCOVERY_ONLY_NOT_FINANCIAL_AUTHORITY'
SPEC = 'system-campaign-p10-ahl2-predecessor-001.json'
SPEC_SHA = '540596362c8d27eaf3f8a5498db70f82550298a70d652d280630215a55334b33'
PRIOR = 'system-campaign-volatility-native-request-001.json'
PRIOR_SHA = 'bcaa266acd6ba06e193f71748dff7c6b9a85ccf3c25c7502ecdc60c11ba9d5c8'
ARM = 'P10'
SID = '1144531901989620662'
CURSOR, NEXT, NATIVE, AFFECTED = '2019-02-01', '2019-02-04', '2019-02-14', '2019-02-15'
POLICY = 'wealth-core-capital-risk-v-v1'
CHECKPOINT = 'research.p10-own-input-epoch-diagnostic-checkpoint/1'
EPOCH = 'research.p10-own-diagnostic-input-epoch/1'
HERE = Path(__file__).resolve().parent


def need(value, reason):
    if not value:
        raise ValueError(reason)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(encoded(value))


def specification():
    raw = (HERE / SPEC).read_bytes()
    need(sha(raw) == SPEC_SHA, 'P10_EXACT_OWN_FROZEN_PREDECESSOR_FILE')
    return validate_spec(json.loads(raw))


def validate_spec(spec):
    need(spec['schema'] == 'research.p10-own-ahl2-diagnostic-predecessor/1'
         and spec['authority'] == TAINT and spec['financial_authority'] is False
         and spec['arm'] == ARM and spec['run_id'] == 41373598360
         and spec['head'] == '4694642dd2e6e5f9362e964f746997d159ec057f'
         and spec['artifact_id'] == 13110583332 and spec['request_sha256'] == PRIOR_SHA,
         'P10_EXACT_OWN_NATIVE427_ARCHIVE')
    need(spec['selected_session'] == CURSOR and spec['next_session'] == NEXT
         and spec['transitions'] == 1 and spec['native_horizon'] == 21
         and spec['source_map']['physical'] == 516 and spec['source_map']['canonical'] == 224
         and len(spec['base']['sources']) == 224 and spec['base']['policy'] == POLICY
         and len(spec['old_descriptors']) == 3
         and spec['source_binding_sha256'] == '1f35cad79d032a9deec064f62306bc276ee5ab21e392406fea1a768cd00f0652',
         'P10_OWN_ORIGINAL_V_MAP_NOT_P01_SAME_COUNT_EPOCH')
    need(spec['input_sha256'] == '4b729049e78470685594a0b55a1753e2c287c30564bc05098dc7093b27a4e6b7'
         and spec['runtime_checkpoint_sha256'] == '2e7fbe8b16a4cea0c866c7c9254ac457fe46486a479ec06fee5f692803ce27b1'
         and spec['diagnostic_checkpoint_sha256'] == '647f70959a360229a1526e837cdb5936727831a8daa83c434ce0cf5eef523bf6',
         'P10_ONLY_OWN_ONE_TRANSITION_COMMITTED_SEED')
    need(digest(spec['full_inventory']) == spec['inventory_sha256']
         and len(spec['full_inventory']) == spec['inventory_members'] == 59,
         'P10_COMPLETE_AUTHENTICATED_OLD_INVENTORY_DESCRIPTOR')
    return spec


def validate_map(value, spec):
    need(value['schema'] == 'research.system-campaign-variant-source/1'
         and value['files'] == len(value['all_sources']) == 516 and value['original_files'] == 514
         and len(value['parameters']) == 25 and value['parameters']['v_horizon'] == 21
         and digest(value['all_sources']) == spec['source_map']['all_sources_sha256']
         and digest(spec['base']['sources']) == spec['source_map']['canonical_sources_sha256'],
         'P10_EXACT_OWN_516_PHYSICAL_AND_224_CANONICAL_MAPS_NO_FALLBACK')
    return value


def function(raw, name, *, owner=None):
    tree = ast.parse(raw)
    body = tree.body
    if owner:
        cls, = [n for n in body if isinstance(n, ast.ClassDef) and n.name == owner]
        body = cls.body
    fn, = [n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    return deepcopy(fn)


def source_contract(files, binding, spec):
    """Only parse authenticated rendered bytes, never import canonical modules."""
    validate_map(binding, spec)
    required = {
        'research/pooled_vacancy_funding/backtest.py': ('input_hash',),
        'research/pooled_vacancy_funding/repair.py': ('load_repair', 'apply_repair'),
        'shared/stock_strategy_shared/wealth_core/capital_risk.py': ('volatility_stop',),
        'shared/stock_strategy_shared/wealth_core/terminal.py': ('apply_terminal',),
        'sentinel/controller/terminal_returns.py': ('values',),
    }
    modules, functions = {}, {}
    for path, names in required.items():
        raw = files[path]
        need(sha(raw) == binding['all_sources'][path], 'P10_EXACT_RENDERED_OWN_SOURCE_BEFORE_AST:' + path)
        modules[path] = sha(raw)
        for name in names:
            fn = function(raw, name)
            functions[path + ':' + name] = dict(sha256=sha(ast.dump(fn, include_attributes=False).encode()),
                                                line=fn.lineno, end_line=fn.end_lineno)
    risk = function(files['shared/stock_strategy_shared/wealth_core/capital_risk.py'], 'volatility_stop')
    guards = [n for n in ast.walk(risk) if isinstance(n, ast.If) and ast.unparse(n.test) ==
              'bar is None or list(bar.signal_sessions or ()) != axis or len(bar.closes) < 21']
    need(len(guards) == 1 and ast.unparse(guards[0].body[0]) ==
         "raise ValueError('REFUSED_VOLATILITY_CAUSAL_AXIS')", 'P10_UNCHANGED_NATIVE21_CAUSAL_REFUSAL_SITE')
    backtest = ast.parse(files['research/pooled_vacancy_funding/backtest.py'])
    overlays = [n for n in ast.walk(backtest) if isinstance(n, ast.If) and ast.unparse(n.test) == 'args.repair_overlay'
                and any(isinstance(x, ast.Assign) and ast.unparse(x.targets[0]) == 'predecessor' for x in n.body)]
    need(len(overlays) == 1, 'P10_EXACT_CANONICAL_INPUT_OVERLAY_SEQUENCE')
    calls = [n for n in ast.walk(overlays[0]) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'replace']
    need(len(calls) == 1 and ast.unparse(calls[0]) == "replace(run, input_sha256=input_hash(base, repairs))",
         'P10_ONLY_CANONICAL_RUNTIME_INPUT_FIELD_REBIND')
    return dict(schema='research.p10-own-source-contract/1', physical_map_sha256=digest(binding['all_sources']),
                canonical_map_sha256=digest(spec['base']['sources']), modules=modules, functions=functions,
                input_overlay_ast_sha256=sha(ast.dump(overlays[0], include_attributes=False).encode()),
                canonical_execution=False, source_or_risk_rule_changed=False)


def physical_tree(root, binding, spec):
    root = Path(root)
    validate_map(binding, spec)
    names = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    need(names == set(binding['all_sources']), 'P10_COMPLETE_OWN516_READONLY_SOURCE_TREE')
    for name, expected in binding['all_sources'].items():
        need(sha((root / name).read_bytes()) == expected, 'P10_ALL_OWN_SOURCE_BYTES_BEFORE_CANONICAL_IMPORT:' + name)
    return source_contract({n:(root / n).read_bytes() for n in (
        'research/pooled_vacancy_funding/backtest.py', 'research/pooled_vacancy_funding/repair.py',
        'shared/stock_strategy_shared/wealth_core/capital_risk.py',
        'shared/stock_strategy_shared/wealth_core/terminal.py', 'sentinel/controller/terminal_returns.py')}, binding, spec)
