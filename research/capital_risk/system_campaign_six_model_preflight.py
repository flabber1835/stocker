"""Ordinary collision checks after all six actual typed inputs are validated."""
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import digest
from system_campaign_outcome_basis import documents, validate_all
from system_campaign_outcome_input import SCHEMA as OUTCOME
from system_campaign_chinook_input import SCHEMA as CHINOOK
import system_campaign_spring2023_preflight as prior
import system_campaign_stock_calendar as stock


class SixModelPreflight:
    def __init__(self, cp, root):
        self.root = Path(root).resolve()
        self.binding = digest(cp)
        self.models, self.body = validate_all(self.root, cp)
        need(set(self.models) == prior.MODELS | {CHINOOK, OUTCOME},
             'SIX_MODEL_ALL_ACTUAL_TYPED_INPUTS_VALIDATED')
        self.model_ids = {'941065113449292610', '732226698577723721',
            '1050970006012443443', '47247117758471252'} | {
            v['security_id'] for k in ('suppress', 'add') for v in self.body[k]}
        visit = prior.compile_visitor(Path(prior.ordinary.__file__).read_bytes())
        need(visit.__closure__ is None, 'SIX_MODEL_ORIGINAL_COLLISION_VISITOR_WITHOUT_CLOSURE')
        self.visit = FunctionType(visit.__code__, dict(visit.__globals__,
            VALIDATED_ADDITIONAL_SCHEMAS=(prior.MODELS - {prior.ALDER}) | {CHINOOK, OUTCOME}),
            visit.__name__, visit.__defaults__)

    def analyze(self, cp, root, catalog):
        need(digest(cp) == self.binding and Path(root).resolve() == self.root,
             'SIX_MODEL_EXACT_FULL_VALIDATED_CHECKPOINT_AND_ROOT')
        documents(self.root, cp)
        value = self.visit(cp, root, catalog)
        extra = prior.extra_collisions(catalog, self.body, self.model_ids)
        need(not extra, 'SIX_MODEL_ALL_TYPED_AND_GUARDED_EVENT_KEYS_DISJOINT')
        value.update(validated_nonordinary_input_sha256=self.models,
            guarded_canonical_keys_checked=sum(len(self.body[k]) for k in ('suppress', 'add')),
            full_actual_input_commitment_verified=True, descriptor_or_financial_checkpoint_projection=False)
        return value

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        need(stock.analyze_new_catalog is prior.ordinary.analyze_new_catalog,
             'SIX_MODEL_EXPECTED_ORIGINAL_STOCK_COLLISION_ENTRY')
        self.original = stock.analyze_new_catalog
        stock.analyze_new_catalog = self.analyze
        return self

    def __exit__(self, *args):
        stock.analyze_new_catalog = self.original
