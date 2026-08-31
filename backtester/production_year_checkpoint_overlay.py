#!/usr/bin/env python3
"""Install deterministic annual checkpoint/resume support on the production replay.

The production engine's SessionState is already a bounded JSON restart image.
This overlay keeps the frozen production implementation untouched and transforms
only the backtester runner function so a long certification can be divided into
calendar-year jobs. Every handoff is content-addressed and fail-closed.
"""
from __future__ import annotations

import inspect
import textwrap


SCHEMA = "backtester.production-year-checkpoint/1"
FULL_DATASET_END = "2026-07-31"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def transformed_main_source(runner) -> str:
    """Return the runner ``main`` source with checkpoint seams installed."""
    text = textwrap.dedent(inspect.getsource(runner.main))

    text = _replace_once(
        text,
        """        canonical_dataset = CanonicalPITDataset(
            Path(canonical_path), expected_start=CHAIN_START, expected_end=END_SESSION
        )
""",
        """        canonical_dataset = CanonicalPITDataset(
            Path(canonical_path), expected_start=CHAIN_START,
            expected_end=os.environ.get('CANONICAL_PIT_EXPECTED_END', END_SESSION),
        )
""",
        "full canonical dataset identity",
    )
    text = _replace_once(
        text,
        """        sessions = list(canonical_dataset.sessions)
""",
        """        sessions = [
            str(value) for value in canonical_dataset.sessions
            if CHAIN_START <= str(value) <= END_SESSION
        ]
        if not sessions or sessions[-1] != END_SESSION:
            raise RuntimeError(
                f'canonical PIT prefix does not end at requested session {END_SESSION}: '
                f'{sessions[-1] if sessions else None}'
            )
""",
        "canonical prefix session axis",
    )

    loop_anchor = """    original_session_breadth = production.session_breadth
    for session, group_iter in itertools.groupby(normalized, key=lambda row: row.vendor.session):
        if session < CHAIN_START:
            continue
"""
    loop_replacement = f"""    original_session_breadth = production.session_breadth
    _checkpoint_input = os.environ.get('PRODUCTION_RESUME_CHECKPOINT', '').strip()
    _checkpoint_output = os.environ.get('PRODUCTION_CHECKPOINT_OUTPUT', '').strip()
    _resume_after = None
    _checkpoint_input_sha256 = None

    def _checkpoint_json_default(value):
        if hasattr(value, 'item'):
            return value.item()
        raise TypeError(f'checkpoint value is not JSON serializable: {{type(value).__name__}}')

    if _checkpoint_input:
        if canonical_dataset is None:
            raise RuntimeError('production checkpoint resume requires canonical PIT input')
        _checkpoint_path = Path(_checkpoint_input).resolve()
        if not _checkpoint_path.is_file():
            raise RuntimeError(f'production checkpoint is missing: {{_checkpoint_path}}')
        _checkpoint_input_sha256 = sha256_file(_checkpoint_path)
        _sidecar = Path(str(_checkpoint_path) + '.sha256')
        if _sidecar.is_file():
            _expected_checkpoint_hash = _sidecar.read_text(encoding='utf-8').strip().split()[0]
            if _checkpoint_input_sha256 != _expected_checkpoint_hash:
                raise RuntimeError(
                    f'production checkpoint hash mismatch: '
                    f'{{_checkpoint_input_sha256}} != {{_expected_checkpoint_hash}}'
                )
        _checkpoint = json.loads(_checkpoint_path.read_text(encoding='utf-8'))
        if _checkpoint.get('schema') != {SCHEMA!r}:
            raise RuntimeError('unsupported production checkpoint schema')
        if _checkpoint.get('main_sha') != EXPECTED_MAIN_SHA:
            raise RuntimeError('production checkpoint main SHA mismatch')
        if _checkpoint.get('backtester_sha') != os.environ.get('BACKTESTER_BRANCH_SHA'):
            raise RuntimeError('production checkpoint backtester SHA mismatch')
        if _checkpoint.get('dataset_hash') != canonical_dataset.dataset_hash:
            raise RuntimeError('production checkpoint canonical dataset mismatch')
        if _checkpoint.get('chain_start') != CHAIN_START:
            raise RuntimeError('production checkpoint chain start mismatch')
        _resume_after = str(_checkpoint.get('end_session') or '')
        if not _resume_after or _resume_after >= END_SESSION:
            raise RuntimeError(
                f'production checkpoint boundary {{_resume_after!r}} does not precede {{END_SESSION}}'
            )
        state_a = SessionState.from_dict(_checkpoint['state_a'])
        state_b = SessionState.from_dict(_checkpoint['state_b'])
        if state_a.last_processed_session != _resume_after or state_b.last_processed_session != _resume_after:
            raise RuntimeError('production checkpoint state/session boundary mismatch')
        accounts = {{}}
        for _name in ('A', 'B'):
            _raw_account = (_checkpoint.get('accounts') or {{}}).get(_name)
            if not isinstance(_raw_account, dict):
                raise RuntimeError(f'production checkpoint lacks account {{_name}}')
            _account = OverlayAccount(_name)
            _account.nav = float(_raw_account['nav'])
            _account.effective = float(_raw_account['effective'])
            _account.pending = float(_raw_account['pending'])
            _account.initialized = bool(_raw_account['initialized'])
            _account.transition_cost = float(_raw_account['transition_cost'])
            _account.transitions = int(_raw_account['transitions'])
            accounts[_name] = _account
        prior_split_factor = defaultdict(
            lambda: 1.0,
            {{str(key): float(value) for key, value in (_checkpoint.get('prior_split_factor') or {{}}).items()}},
        )
        seen_count = defaultdict(
            int,
            {{str(key): int(value) for key, value in (_checkpoint.get('seen_count') or {{}}).items()}},
        )
        prior_signal_close = {{
            str(key): (int(value[0]), float(value[1]))
            for key, value in (_checkpoint.get('prior_signal_close') or {{}}).items()
        }}
        latest_ticker_by_sid = {{
            str(key): str(value)
            for key, value in (_checkpoint.get('latest_ticker_by_sid') or {{}}).items()
        }}
        prior_core_close = (
            None if _checkpoint.get('prior_core_close') is None
            else float(_checkpoint['prior_core_close'])
        )
        daily_rows = list(_checkpoint.get('daily_rows') or [])
        expected_pointer = int(_checkpoint['expected_pointer'])
        _expected_pointer = sum(1 for value in sessions if value <= _resume_after)
        if expected_pointer != _expected_pointer:
            raise RuntimeError(
                f'production checkpoint session pointer mismatch: '
                f'{{expected_pointer}} != {{_expected_pointer}}'
            )
        if not daily_rows or str(daily_rows[-1].get('date')) != _resume_after:
            raise RuntimeError('production checkpoint cumulative daily evidence is incomplete')
        print(
            f'[CHECKPOINT RESUME] through={{_resume_after}} sessions={{expected_pointer:,}} '
            f'sha256={{_checkpoint_input_sha256}}',
            flush=True,
        )

    for session, group_iter in itertools.groupby(normalized, key=lambda row: row.vendor.session):
        if session < CHAIN_START:
            continue
        if _resume_after is not None and session <= _resume_after:
            continue
"""
    text = _replace_once(
        text, loop_anchor, loop_replacement, "production checkpoint resume boundary"
    )

    finish_anchor = """    production.session_breadth = original_session_breadth
    if expected_pointer != len(sessions):
"""
    finish_replacement = f"""    production.session_breadth = original_session_breadth
    if _checkpoint_output:
        if canonical_dataset is None:
            raise RuntimeError('production checkpoint output requires canonical PIT input')
        if state_a.last_processed_session != END_SESSION or state_b.last_processed_session != END_SESSION:
            raise RuntimeError('cannot checkpoint an incomplete production segment')
        _checkpoint_payload = {{
            'schema': {SCHEMA!r},
            'main_sha': EXPECTED_MAIN_SHA,
            'backtester_sha': os.environ.get('BACKTESTER_BRANCH_SHA'),
            'dataset_hash': canonical_dataset.dataset_hash,
            'chain_start': CHAIN_START,
            'measurement_start': os.environ.get('CERTIFICATION_MEASUREMENT_START'),
            'end_session': END_SESSION,
            'session_hash': canonical_dataset.session_hash(END_SESSION),
            'expected_pointer': int(expected_pointer),
            'previous_checkpoint_sha256': _checkpoint_input_sha256,
            'state_a': state_a.to_dict(),
            'state_b': state_b.to_dict(),
            'accounts': {{
                name: {{
                    'nav': float(account.nav),
                    'effective': float(account.effective),
                    'pending': float(account.pending),
                    'initialized': bool(account.initialized),
                    'transition_cost': float(account.transition_cost),
                    'transitions': int(account.transitions),
                }}
                for name, account in sorted(accounts.items())
            }},
            'prior_split_factor': dict(sorted(
                (str(key), float(value)) for key, value in prior_split_factor.items()
            )),
            'seen_count': dict(sorted(
                (str(key), int(value)) for key, value in seen_count.items()
            )),
            'prior_signal_close': dict(sorted(
                (str(key), [int(value[0]), float(value[1])])
                for key, value in prior_signal_close.items()
            )),
            'latest_ticker_by_sid': dict(sorted(
                (str(key), str(value)) for key, value in latest_ticker_by_sid.items()
            )),
            'prior_core_close': (
                None if prior_core_close is None else float(prior_core_close)
            ),
            'daily_rows': daily_rows,
        }}
        _checkpoint_path = Path(_checkpoint_output).resolve()
        _checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        _checkpoint_tmp = _checkpoint_path.with_name(_checkpoint_path.name + '.tmp')
        _checkpoint_tmp.write_text(
            json.dumps(
                _checkpoint_payload,
                indent=2,
                sort_keys=True,
                allow_nan=False,
                default=_checkpoint_json_default,
            ) + '\n',
            encoding='utf-8',
        )
        os.replace(_checkpoint_tmp, _checkpoint_path)
        _checkpoint_hash = sha256_file(_checkpoint_path)
        Path(str(_checkpoint_path) + '.sha256').write_text(
            f'{{_checkpoint_hash}}  {{_checkpoint_path.name}}\n',
            encoding='utf-8',
        )
        print(
            f'[CHECKPOINT WRITE] through={{END_SESSION}} sessions={{expected_pointer:,}} '
            f'sha256={{_checkpoint_hash}} path={{_checkpoint_path}}',
            flush=True,
        )
    if expected_pointer != len(sessions):
"""
    text = _replace_once(
        text, finish_anchor, finish_replacement, "production checkpoint write boundary"
    )
    return text


def install(runner) -> None:
    """Replace ``runner.main`` with the deterministic checkpointed variant."""
    text = transformed_main_source(runner)
    compile(text, "<checkpointed-production-runner-main>", "exec")
    exec(text, runner.__dict__)
    if runner.main.__module__ != runner.__name__:
        raise RuntimeError("checkpointed production main bound to wrong module")
