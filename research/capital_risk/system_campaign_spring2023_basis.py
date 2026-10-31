"""Exact factual delta with all existing model semantics unchanged."""
from copy import deepcopy
from full_system_benchmark import need
from system_campaign_facts import digest


def require_exact_delta(before, after, catalog, commitments):
    expected = deepcopy(before)
    factual = expected['factual_semantics']
    for field in ('suppress', 'add'):
        new = ([dict(session=t['native_session'], security_id=t['security_id'], term_sha256=t['native_term_sha256'])
                for t in catalog['terms']] if field == 'suppress' else [t['added'] for t in catalog['terms']])
        indexed = {(v['session'], v['security_id']): v for v in factual[field]}
        need(len(indexed) == len(factual[field]), 'SPRING2023_UNIQUE_OLD_COMMON_FACTUAL_KEYS')
        for item in new:
            key = item['session'], item['security_id']
            need(key not in indexed, 'SPRING2023_NO_COMMON_FACTUAL_KEY_OVERRIDE')
            indexed[key] = deepcopy(item)
        factual[field] = [indexed[k] for k in sorted(indexed)]
    stem = catalog['commitment_group']['reference_stem']
    need(set(commitments) == {stem + k for k in ('catalog', 'loader', 'private')}
         and not set(factual['declared_fact_compilers']) & set(commitments),
         'SPRING2023_EXACT_THREE_NEW_UNREDEFINED_COMMON_COMMITMENTS')
    factual['declared_fact_compilers'].update(commitments)
    expected['factual_semantics_sha256'] = digest(factual)
    need(after == expected, 'SPRING2023_EXACT_FACTUAL_DELTA_ALL_FOUR_MODEL_SEMANTICS_UNCHANGED')
    return True
