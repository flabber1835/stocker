"""Source-bound factual packet corrections; no strategy or account operations."""
import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from full_system_benchmark import need, save

REPAIR_SHA = '1112f91ab01c6b633fd6e7b2c089aa02367d2fc7fbc152a654da6620d753b152'
CATALOG_REF = 'research:system-optimization-002/common-factual-catalog/1'
COMPILER_REF = 'research:system-optimization-002/factual-input-compiler/1'
HYDRATED_REF = 'research:system-optimization-002/private-hydrated-factual-catalog/1'
IDENTITIES = {'224580439420294771': '234488913323173693',
              '37439132904117100': '285304847559167677', 'GE': 'FNF', 'GEV': 'BKI'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def compile_input_function(raw, globals_):
    """Reuse the authenticated pure function with only named identity substitutions."""
    need(sha(raw) == REPAIR_SHA, 'FACTUAL_FROZEN_REPAIR_SOURCE')
    node, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef)
             and n.name == '_apply_spinoff_repair']
    counts = {key: 0 for key in IDENTITIES}
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in IDENTITIES:
            counts[n.value] += 1
            n.value = IDENTITIES[n.value]
    need(counts == {'224580439420294771': 2, '37439132904117100': 1, 'GE': 1, 'GEV': 1},
         'FACTUAL_EXACT_IDENTITY_LITERAL_SITES')
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = dict(globals_)
    exec(compile(module, '<source-bound-FNF-input-function>', 'exec'), namespace)
    return namespace['_apply_spinoff_repair']


class FactualInputs:
    def __init__(self, catalog_path):
        self.path = Path(catalog_path)
        self.raw = self.path.read_bytes()
        self.catalog = json.loads(self.raw)
        need(self.catalog['schema'] == 'research.system-campaign-common-factual-catalog/1'
             and not self.catalog['canonical_financial_source_changed']
             and not self.catalog['production_contacted'], 'FACTUAL_CATALOG_SCOPE')
        self.catalog_sha = sha(self.raw)
        self.compiler_sha = sha(Path(__file__).read_bytes())
        self.document_sha = digest(self.catalog)
        self.hydrated_sha = None

    def hydrate(self, output):
        """Resolve private quotes only inside the offline hosted financial worker."""
        import os, zipfile
        need(os.environ.get('FULL_SYSTEM_HOSTED') == '1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'), 'HOSTED_PRIVATE_FACT_HYDRATION_ONLY')
        from research.pooled_input_support import inputs
        from research.bounded_20y.run import vendor
        wanted = {('2017-10-02', '234488913323173693'), ('2017-10-02', '285304847559167677')}
        for item in self.catalog['terms']:
            if item['proxy']:
                wanted.add((item['proxy']['session'], item['added']['delivered_security_id']))
        rows = {}
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
            for year in sorted({day[:4] for day, _ in wanted}):
                for row in inputs._archive_rows(archive, f'observations-{year}.csv.gz'):
                    key = row['session'], row['security_id']
                    if key in wanted:
                        need(key not in rows, 'FACTUAL_UNIQUE_PRIVATE_QUOTE')
                        rows[key] = row
        need(set(rows) == wanted, 'FACTUAL_ALL_PRIVATE_QUOTES_PRESENT')
        from dataclasses import asdict
        spin = self.catalog['fnf']
        for name, sid in (('parent', '234488913323173693'), ('child', '285304847559167677')):
            value = asdict(vendor(rows[('2017-10-02', sid)]))
            need(digest(value) == spin[name+'_bar_sha256'], 'FACTUAL_PRIVATE_BAR_HASH')
            spin[name+'_bar'] = value
        spin['cash_proxy_per_parent'] = str(spin['parent_bar']['dividend_per_share'])
        spin['added']['cash_in_lieu_price'] = str(spin['child_bar']['raw_open'])
        for item in self.catalog['terms']:
            if item['proxy']:
                row = rows[(item['proxy']['session'], item['added']['delivered_security_id'])]
                need(digest(row) == item['proxy']['source_observation_sha256'], 'FACTUAL_PRIVATE_OBSERVATION_HASH')
                value = float(row['raw_open'])
                need(value > 0, 'FACTUAL_POSITIVE_PRIVATE_OPEN')
                item['added']['cash_in_lieu_price_per_delivered_share'] = value
        save(output, self.catalog)
        self.hydrated_sha = sha(Path(output).read_bytes())
        self.document_sha = digest(self.catalog)

    def evidence(self):
        rows = [{'reference': CATALOG_REF, 'description': 'Exact common primary-source factual catalog; declared CIL/daily-boundary proxies retained.', 'sha256': self.catalog_sha},
                {'reference': COMPILER_REF, 'description': 'Exact scoped packet input compiler; canonical financial source unchanged.', 'sha256': self.compiler_sha}]
        if self.hydrated_sha is not None:
            rows.append({'reference': HYDRATED_REF, 'description': 'Exact privately hydrated quote catalog from the frozen archive, retained only in encrypted evidence.', 'sha256': self.hydrated_sha})
        return rows

    def _bound(self, repair):
        expected = {v['reference']: v['sha256'] for v in self.evidence()}
        found = [(v.reference, v.sha256) for v in repair.source_evidence if v.reference in expected]
        if not found:
            return False
        need(len(found) == len(expected) and dict(found) == expected, 'FACTUAL_CATALOG_COMPILER_COMMITMENTS')
        need(digest(self.catalog) == self.document_sha, 'FACTUAL_CATALOG_UNCHANGED')
        need(repair.earliest_affected_session <= '2017-08-09' and repair._resume_session < '2017-08-09',
             'FACTUAL_ALL_CORRECTIONS_FUTURE')
        return True

    def __enter__(self):
        need(self.hydrated_sha is not None, 'FACTUAL_PRIVATE_QUOTES_HYDRATED')
        from research.pooled_vacancy_funding import backtest, repair
        from sentinel.core.spinoffs import SpinoffDistribution
        self.backtest, self.original = backtest, backtest.apply_repair
        self.function = compile_input_function(Path(repair.__file__).read_bytes(), vars(repair))
        spin = self.catalog['fnf']
        fields = spin['added']
        need(fields['session'] == '2017-10-02' and fields['parent_security_id'] == IDENTITIES['224580439420294771']
             and fields['child_security_id'] == IDENTITIES['37439132904117100']
             and fields['child_shares_per_parent'] == '0.3066322'
             and fields['policy'] == 'LIQUIDATE_CHILD_AT_OPEN'
             and spin['cash_proxy_semantics'] == 'IN_KIND_CHILD_DISTRIBUTION_NOT_ADDITIONAL_CASH',
             'FACTUAL_TYPED_FNF_SCOPE')
        term = SpinoffDistribution(**fields)
        self.spin = SimpleNamespace(
            suppress=tuple(SimpleNamespace(term_sha256=v['term_sha256']) for v in spin['native']),
            add=(SimpleNamespace(cash_in_lieu_price=fields['cash_in_lieu_price'], terms=lambda: term),),
            parent_bar_sha256=spin['parent_bar_sha256'], child_bar_sha256=spin['child_bar_sha256'],
            cash_proxy_per_parent=spin['cash_proxy_per_parent'], earliest_affected_session='2017-10-02')
        def apply(packet, loaded):
            changed = self.original(packet, loaded)
            if not self._bound(loaded) or packet.day != '2017-10-02':
                return changed
            local = copy.copy(self.spin)
            local._resume_session = loaded._resume_session
            return self.function(changed, local)
        backtest.apply_repair = apply
        return self

    def __exit__(self, *args):
        self.backtest.apply_repair = self.original

    def overlay(self, checkpoint, output, retained_origin_document=None):
        """Bind common facts to THIS exact canonical predecessor; no state edits."""
        cursor = checkpoint['source_cursor']
        need(cursor < '2017-08-09', 'FACTUAL_UNCONSUMED_PREDECESSOR')
        document = {'schema': 'terminal-repair/1',
                    'predecessor_checkpoint_sha256': checkpoint['run']['checkpoint_sha256'],
                    'source_evidence': self.evidence(), 'suppress': [], 'add': []}
        if not checkpoint['repairs']:
            need(retained_origin_document is not None and checkpoint['completed'] == 0
                 and checkpoint['run']['state']['last_processed_session'] is None,
                 'FACTUAL_REUSE_OWN_ZERO_ORIGIN_ONLY')
            old = retained_origin_document
            need(old['predecessor_checkpoint_sha256'] == document['predecessor_checkpoint_sha256'],
                 'FACTUAL_OWN_ORIGIN_BINDING')
            for name in ('suppress', 'add'):
                need(all(v['session'] > cursor for v in old[name]), 'FACTUAL_FUTURE_RETAINED_TERMS')
                document[name].extend(old[name])
            document['source_evidence'].extend(old['source_evidence'])
        for item in self.catalog['terms']:
            need(digest(item['native']) == item['native_term_sha256'], 'FACTUAL_NATIVE_TERM_DIGEST')
            n = item['native']
            document['suppress'].append({'session': n['session'], 'security_id': n['security_id'],
                                        'term_sha256': item['native_term_sha256']})
            document['add'].append(item['added'])
        save(output, document)
        from research.pooled_vacancy_funding.repair import load_repair
        loaded = load_repair(output, resume_session=cursor,
                             predecessor_checkpoint_sha256=checkpoint['run']['checkpoint_sha256'])
        need(self._bound(loaded), 'FACTUAL_OWN_LOADED_BINDING')
        return loaded
