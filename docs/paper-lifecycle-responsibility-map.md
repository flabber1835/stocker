# Sentinel paper lifecycle responsibility map

> Historical decomposition record: every path, line number, and consumer below
> describes the Step 4 base named in the next paragraph. It is retained as the
> provenance for the resulting package and is not a current ownership/import
> inventory. Current CLI and authority ownership is recorded in
> `docs/final-simplification-freeze.md`.

Generated from the exact `sentinel/paper.py` source on the Step 4 base.

- Source lines: **3202**
- Source SHA-256: `c14cc619ca19e91b53e3f618543ea782e97f5a87bdde65af6370bd313bd63ffe`
- Top-level callables/classes: **59**
- Repository consumer files: **39**

## Proposed cohesive ownership

| Owner | Top-level definitions |
|---|---:|
| `model` | 6 |
| `inspection` | 5 |
| `validation` | 5 |
| `cash` | 7 |
| `reconciliation` | 17 |
| `preparation` | 8 |
| `execution` | 10 |
| `finalization` | 1 |

## Normal lifecycle roots and static reachability

### `prepare_paper_plan`

`PaperActivationRefused`, `PaperRetryableRefused`, `PreOpenShareUnitAuthorityUnavailable`, `PreparationResult`, `_account_endpoint_lag_is_live`, `_account_or_refuse`, `_action_lookup`, `_assert_concordance_witness_authority`, `_assert_deterministic_plan_id`, `_assert_plan_authorities`, `_broker_cash_state_or_refuse`, `_cash_authority_or_refuse`, `_clean_or_refuse`, `_default_paper_strategy`, `_execution_window_or_refuse`, `_finalize_due_succeeded_cycle_or_refuse`, `_fresh_connection_factory`, `_fresh_warmed_state`, `_guard_broker`, `_hash`, `_load_marks_and_tickers`, `_missed_sessions`, `_observation_economics`, `_official_preopen_cutoff`, `_post_projection_action_multipliers`, `_preopen_active_security_ids`, `_preopen_views_or_none`, `_readiness_or_refuse`, `_record_due_close_nav_or_refuse`, `_record_due_fill_interval_or_refuse`, `_require_certified_paper_broker`, `_revalidate_preopen_authority_or_refuse`, `_state_and_plan_or_refuse`, `_target_action_lookup`, `_target_action_multipliers`, `_validate_automation_grant`, `_validate_broker_grant`, `prepare_paper_plan`

### `inspect_paper_account`

`PaperAccountInspection`, `PaperActivationRefused`, `_inspection_account_or_refuse`, `_require_certified_paper_broker`, `inspect_paper_account`

## Complete top-level definition map

| Lines | Definition | Kind | Proposed owner | Calls | DB/transaction | Broker calls | Raises | Policy helper |
|---|---|---|---|---|---|---|---|---|
| 103–113 | `_assert_concordance_witness_authority(state ,authorization_mode)` | function | `validation` | PaperActivationRefused | — | — | PaperActivationRefused | yes |
| 116–144 | `_default_paper_strategy()` | function | `validation` | PaperActivationRefused | rollback | — | PaperActivationRefused | yes |
| 147–148 | `PaperActivationRefusedclass` | class | `model` | — | — | — | — | no |
| 151–152 | `PaperRetryableRefusedclass` | class | `model` | — | — | — | — | no |
| 155–156 | `PreOpenShareUnitAuthorityUnavailableclass` | class | `model` | — | — | — | — | no |
| 160–271 | `PaperAccountInspectionclass` | class | `model` | — | — | — | — | no |
| 275–297 | `PreparationResultclass` | class | `model` | — | — | — | — | no |
| 301–320 | `ExecutionResultclass` | class | `model` | — | — | — | — | no |
| 323–352 | `_require_certified_paper_broker(broker)` | function | `inspection` | PaperActivationRefused | — | — | PaperActivationRefused | yes |
| 355–397 | `_inspection_account_or_refuse(snapshot ,expected_account)` | function | `inspection` | PaperActivationRefused | — | — | PaperActivationRefused | yes |
| 400–439 | `inspect_paper_account(* ,conn ,broker ,base_url ,expected_account)` | async function | `inspection` | PaperAccountInspection, PaperActivationRefused, _inspection_account_or_refuse, _require_certified_paper_broker | SELECT, conn.cursor | broker.account_snapshot, broker.observe | PaperActivationRefused | no |
| 442–444 | `_hash(value)` | function | `validation` | — | — | — | — | no |
| 447–460 | `_readiness_or_refuse(conn ,* ,now_et=None)` | function | `validation` | PaperRetryableRefused | — | — | PaperRetryableRefused | yes |
| 463–478 | `_execution_observation_time(value)` | function | `execution` | — | — | — | — | yes |
| 481–489 | `_execution_window_or_refuse(session ,now_et)` | function | `execution` | PaperRetryableRefused | — | — | PaperRetryableRefused | yes |
| 492–505 | `_clean_or_refuse(result ,* ,purpose)` | function | `reconciliation` | — | — | — | error | yes |
| 508–524 | `_dual_mutation_observation_or_refuse(result)` | function | `reconciliation` | PaperActivationRefused, _clean_or_refuse | — | — | PaperActivationRefused | yes |
| 527–534 | `_account_evidence_is_quiescent(conn ,* ,deployment ,observation)` | function | `inspection` | — | — | — | — | no |
| 537–571 | `_observation_economics(observation)` | function | `execution` | — | — | — | — | yes |
| 574–593 | `_account_economics(snapshot)` | function | `cash` | — | — | — | — | yes |
| 596–676 | `_account_endpoint_lag_is_live(conn ,* ,plan ,deployment ,account ,expected_cash ,observation ,observed_at)` | function | `reconciliation` | PaperActivationRefused, _hash, _observation_economics | CREATE, INSERT, LOCK, SELECT, commit, conn.cursor | — | PaperActivationRefused | yes |
| 679–718 | `_settled_account_evidence_bracket(* ,conn ,broker ,binding ,expected_account ,deployment ,initial_result ,actions ,dual_mode ,clock)` | async function | `reconciliation` | PaperRetryableRefused, _account_economics, _account_evidence_is_quiescent, _account_or_refuse, _broker_cash_state_or_refuse, _clean_or_refuse, _dual_mutation_observation_or_refuse, _observation_economics | — | broker.account_snapshot | PaperRetryableRefused | yes |
| 721–768 | `_account_or_refuse(snapshot ,binding ,expected_account)` | function | `cash` | PaperActivationRefused, PaperRetryableRefused | — | — | PaperActivationRefused, PaperRetryableRefused, error | yes |
| 771–783 | `_recovery_account_identity_or_refuse(snapshot ,binding ,expected_account)` | function | `inspection` | PaperActivationRefused | — | — | PaperActivationRefused | yes |
| 786–804 | `_broker_cash_state_or_refuse(conn ,* ,broker ,binding ,through)` | async function | `cash` | PaperActivationRefused, PaperRetryableRefused | LOCK | — | PaperActivationRefused, PaperRetryableRefused | yes |
| 807–834 | `_record_due_close_nav_or_refuse(conn ,* ,broker ,deployment ,session)` | async function | `execution` | PaperActivationRefused, PaperRetryableRefused | — | — | PaperActivationRefused, PaperRetryableRefused | yes |
| 837–920 | `_record_due_fill_interval_or_refuse(conn ,* ,broker ,deployment ,plan ,session ,required_through)` | async function | `reconciliation` | PaperActivationRefused, PaperRetryableRefused | — | — | PaperActivationRefused, PaperRetryableRefused, trial_fills.TrialFillIntervalRefused | yes |
| 923–1026 | `_finalize_due_succeeded_cycle_or_refuse(conn ,* ,broker ,deployment ,plan ,reconciliation ,account ,activity_state ,observation_started_at ,observed_at ,target_actions ,observation_target_actions ,clock)` | async function | `reconciliation` | PaperActivationRefused, PaperRetryableRefused, _post_projection_action_multipliers, _record_due_close_nav_or_refuse, _record_due_fill_interval_or_refuse, _target_action_multipliers | — | — | PaperActivationRefused, PaperRetryableRefused, target_reprojection.TargetProjectionRefused | yes |
| 1029–1119 | `_cash_authority_or_refuse(conn ,* ,plan ,deployment ,account ,observation ,activity_state=None ,permit_new_activity=False ,endpoint_lag_observed_at=None)` | function | `reconciliation` | PaperActivationRefused, PaperRetryableRefused, _account_endpoint_lag_is_live | — | — | PaperActivationRefused, PaperRetryableRefused | yes |
| 1122–1150 | `_load_marks_and_tickers(conn ,state ,session)` | function | `preparation` | — | SELECT, conn.cursor | — | — | yes |
| 1153–1160 | `_missed_sessions(cursor ,through)` | function | `validation` | PaperActivationRefused | — | — | PaperActivationRefused | yes |
| 1163–1204 | `_fresh_warmed_state(conn ,* ,through ,count ,account ,controller_config ,strategy_identity ,publication_version ,authorization_mode='HISTORICALLY_CERTIFIED')` | function | `cash` | PaperActivationRefused | — | — | PaperActivationRefused | yes |
| 1207–1213 | `_assert_deterministic_plan_id(plan)` | function | `execution` | PaperActivationRefused | — | — | PaperActivationRefused | yes |
| 1216–1225 | `_fresh_connection_factory(conn)` | function | `preparation` | PaperActivationRefused | — | — | PaperActivationRefused | yes |
| 1228–1306 | `_validate_automation_grant(conn ,grant)` | function | `reconciliation` | PaperActivationRefused | — | — | PaperActivationRefused | yes |
| 1309–1415 | `_validate_broker_grant(conn ,grant ,_operation ,result ,* ,now_provider ,strategy_provider ,dual_shadow_observation_id=None ,dual_shadow_starting_cash=None)` | function | `reconciliation` | PaperActivationRefused, _assert_plan_authorities, _execution_window_or_refuse, _readiness_or_refuse, _state_and_plan_or_refuse, _validate_automation_grant | LOCK | — | PaperActivationRefused | yes |
| 1418–1438 | `_guard_broker(* ,conn ,broker ,grant ,base_url ,now_provider ,strategy_provider ,automation_config_sha256=None ,dual_shadow_observation_id=None ,dual_shadow_starting_cash=None)` | function | `cash` | _fresh_connection_factory, _validate_broker_grant | — | — | — | yes |
| 1441–1942 | `prepare_paper_plan(* ,conn ,broker ,base_url ,through ,expected_account=None ,warmup_sessions=252 ,controller_config=None ,strategy_identity=None ,now_et=None ,automation_grant=None ,automation_config_sha256=None ,dual_shadow_observation_id=None ,dual_shadow_starting_cash=None)` | async function | `preparation` | PaperActivationRefused, PaperRetryableRefused, PreOpenShareUnitAuthorityUnavailable, PreparationResult, _account_or_refuse, _action_lookup, _assert_concordance_witness_authority, _assert_deterministic_plan_id, _assert_plan_authorities, _broker_cash_state_or_refuse, _cash_authority_or_refuse, _clean_or_refuse, _default_paper_strategy, _finalize_due_succeeded_cycle_or_refuse, _fresh_warmed_state, _guard_broker, _load_marks_and_tickers, _missed_sessions, _official_preopen_cutoff, _preopen_active_security_ids, _preopen_views_or_none, _readiness_or_refuse, _require_certified_paper_broker, _revalidate_preopen_authority_or_refuse, _target_action_lookup | LOCK, commit | broker.account_snapshot | PaperActivationRefused, PaperRetryableRefused, PreOpenShareUnitAuthorityUnavailable | no |
| 1945–1957 | `_state_and_plan_or_refuse(conn)` | function | `execution` | PaperActivationRefused, _assert_deterministic_plan_id | — | — | PaperActivationRefused | yes |
| 1960–2006 | `_assert_plan_authorities(conn ,* ,state ,plan ,binding ,pinned ,frontier ,today ,runtime_identity ,rollout ,require_effective_today=True)` | function | `finalization` | PaperActivationRefused, _assert_deterministic_plan_id, _hash | — | — | PaperActivationRefused | yes |
| 2009–2026 | `_action_lookup(conn ,state ,through)` | function | `reconciliation` | — | SELECT, conn.cursor | — | — | yes |
| 2029–2041 | `_target_action_lookup(conn ,plan ,through)` | function | `reconciliation` | — | — | — | — | yes |
| 2044–2066 | `_target_action_multipliers(plan ,actions)` | function | `preparation` | — | — | — | — | yes |
| 2069–2081 | `_post_projection_action_multipliers(projection ,actions)` | function | `cash` | — | — | — | — | yes |
| 2084–2107 | `_preopen_active_security_ids(* ,plan ,commands ,actions)` | function | `reconciliation` | — | UPDATE | — | — | yes |
| 2110–2144 | `_informational_active_symbols(* ,active_security_ids ,commands ,observation ,sizing_proof)` | function | `execution` | PaperActivationRefused | — | — | PaperActivationRefused | yes |
| 2147–2161 | `_plan_deltas(* ,target_basket ,observation ,minimum_quantity_increment)` | function | `preparation` | — | UPDATE | — | — | yes |
| 2164–2179 | `_provably_clean_empty_noop(* ,deltas ,commands ,observation)` | function | `preparation` | — | commit | — | — | yes |
| 2182–2202 | `_preopen_views_or_none(conn ,* ,plan ,active_security_ids ,required_cutoff_at ,evaluated_at ,actions ,target_actions)` | function | `preparation` | PreOpenShareUnitAuthorityUnavailable | — | — | PreOpenShareUnitAuthorityUnavailable | yes |
| 2205–2220 | `_revalidate_preopen_authority_or_refuse(* ,authority ,plan ,commands ,actions ,required_cutoff_at ,evaluated_at)` | function | `reconciliation` | PreOpenShareUnitAuthorityUnavailable, _preopen_active_security_ids | — | — | PreOpenShareUnitAuthorityUnavailable | yes |
| 2223–2226 | `_official_preopen_cutoff(plan)` | function | `execution` | — | — | — | — | yes |
| 2229–2321 | `_target_projection_or_refuse(conn ,* ,state ,plan ,binding ,broker ,through ,actions ,target_actions ,require_existing=False ,persist_projection=True ,expected_projection=None)` | function | `reconciliation` | PaperActivationRefused | — | — | PaperActivationRefused, target_reprojection.TargetProjectionRefused | yes |
| 2324–2394 | `_instrument_map(conn ,broker ,state ,plan ,observation ,target_basket=None)` | async function | `preparation` | PaperActivationRefused, PaperRetryableRefused | commit | — | PaperActivationRefused, PaperRetryableRefused | yes |
| 2397–2759 | `_execute_current_paper_plan(* ,conn ,broker ,base_url ,grant ,today=None ,automation_config_sha256=None ,dual_shadow_observation_id=None ,dual_shadow_starting_cash=None)` | async function | `reconciliation` | ExecutionResult, PaperActivationRefused, PaperRetryableRefused, PreOpenShareUnitAuthorityUnavailable, _account_evidence_is_quiescent, _account_or_refuse, _action_lookup, _assert_deterministic_plan_id, _assert_plan_authorities, _broker_cash_state_or_refuse, _cash_authority_or_refuse, _clean_or_refuse, _default_paper_strategy, _dual_mutation_observation_or_refuse, _execution_observation_time, _execution_window_or_refuse, _guard_broker, _informational_active_symbols, _instrument_map, _official_preopen_cutoff, _plan_deltas, _post_projection_action_multipliers, _preopen_active_security_ids, _preopen_views_or_none, _provably_clean_empty_noop, _readiness_or_refuse, _require_certified_paper_broker, _revalidate_preopen_authority_or_refuse, _settled_account_evidence_bracket, _state_and_plan_or_refuse, _target_action_lookup, _target_projection_or_refuse, _validate_automation_grant | CREATE, commit, rollback | broker.account_snapshot | PaperActivationRefused, PaperRetryableRefused, PreOpenShareUnitAuthorityUnavailable | yes |
| 2762–2781 | `execute_paper_plan(* ,conn ,broker ,base_url ,confirm_account ,confirm_plan_id ,confirm_effective_session ,confirm_submit ,today=None)` | async function | `execution` | PaperActivationRefused, _execute_current_paper_plan | — | — | PaperActivationRefused | no |
| 2784–2797 | `execute_automated_paper_plan(* ,conn ,broker ,base_url ,grant ,automation_config_sha256 ,today=None ,dual_shadow_observation_id=None ,dual_shadow_starting_cash=None)` | async function | `cash` | _execute_current_paper_plan | — | — | — | no |
| 2800–3044 | `recover_automated_paper_cycle(* ,conn ,broker ,base_url ,grant ,automation_config_sha256 ,dual_shadow_observation_id=None ,dual_shadow_starting_cash=None)` | async function | `reconciliation` | PaperActivationRefused, PaperRetryableRefused, PreOpenShareUnitAuthorityUnavailable, _account_evidence_is_quiescent, _action_lookup, _assert_deterministic_plan_id, _broker_cash_state_or_refuse, _cash_authority_or_refuse, _default_paper_strategy, _dual_mutation_observation_or_refuse, _guard_broker, _official_preopen_cutoff, _post_projection_action_multipliers, _preopen_active_security_ids, _preopen_views_or_none, _recovery_account_identity_or_refuse, _require_certified_paper_broker, _revalidate_preopen_authority_or_refuse, _settled_account_evidence_bracket, _target_action_lookup, _target_projection_or_refuse, _validate_automation_grant | commit | broker.account_snapshot | AuthorityRefused, PaperActivationRefused, PaperRetryableRefused, PreOpenShareUnitAuthorityUnavailable, informational_paper_mirror.InformationalPaperMirrorPending | no |
| 3047–3178 | `current_paper_plan(conn ,* ,base_url=DEFAULT_BASE_URL ,dual_shadow_observation_id=None ,dual_shadow_starting_cash=None)` | function | `reconciliation` | PaperActivationRefused, PaperRetryableRefused, _assert_deterministic_plan_id, _default_paper_strategy, _hash, _state_and_plan_or_refuse | UPDATE | — | PaperActivationRefused, PaperRetryableRefused | no |
| 3181–3191 | `build_security_resolver(conn ,session)` | function | `execution` | — | — | — | — | no |

## Required responsibility index

### account inspection

`_execute_current_paper_plan`, `_inspection_account_or_refuse`, `_settled_account_evidence_bracket`, `inspect_paper_account`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### account identity verification

`PaperAccountInspection`, `_account_economics`, `_account_endpoint_lag_is_live`, `_account_or_refuse`, `_assert_plan_authorities`, `_execute_current_paper_plan`, `_inspection_account_or_refuse`, `_observation_economics`, `_recovery_account_identity_or_refuse`, `_settled_account_evidence_bracket`, `_validate_automation_grant`, `_validate_broker_grant`, `inspect_paper_account`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### broker capability inspection

`_execute_current_paper_plan`, `_finalize_due_succeeded_cycle_or_refuse`, `_record_due_close_nav_or_refuse`, `_record_due_fill_interval_or_refuse`, `_target_projection_or_refuse`

### broker construction

`_guard_broker`

### paper-only endpoint enforcement

`_execute_current_paper_plan`, `_guard_broker`, `current_paper_plan`, `execute_automated_paper_plan`, `execute_paper_plan`, `inspect_paper_account`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### preparation

`PaperActivationRefused`, `PreparationResult`, `_cash_authority_or_refuse`, `_finalize_due_succeeded_cycle_or_refuse`, `_validate_automation_grant`, `_validate_broker_grant`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### strategy/target-book preparation

`_assert_concordance_witness_authority`, `_assert_plan_authorities`, `_default_paper_strategy`, `_execute_current_paper_plan`, `_fresh_warmed_state`, `_guard_broker`, `_validate_broker_grant`, `current_paper_plan`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### state warming or initialization

`PreparationResult`, `_fresh_warmed_state`, `inspect_paper_account`, `prepare_paper_plan`

### portfolio/state restoration

`prepare_paper_plan`

### reconciliation

`PreparationResult`, `_account_endpoint_lag_is_live`, `_action_lookup`, `_cash_authority_or_refuse`, `_clean_or_refuse`, `_dual_mutation_observation_or_refuse`, `_execute_current_paper_plan`, `_finalize_due_succeeded_cycle_or_refuse`, `_preopen_active_security_ids`, `_record_due_fill_interval_or_refuse`, `_revalidate_preopen_authority_or_refuse`, `_settled_account_evidence_bracket`, `_target_action_lookup`, `_target_projection_or_refuse`, `_validate_automation_grant`, `_validate_broker_grant`, `current_paper_plan`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### terminal recovery

`_account_endpoint_lag_is_live`, `_preopen_active_security_ids`

### cash inspection

`_broker_cash_state_or_refuse`, `_cash_authority_or_refuse`

### cash authority

`_broker_cash_state_or_refuse`, `_cash_authority_or_refuse`, `_execute_current_paper_plan`, `_finalize_due_succeeded_cycle_or_refuse`, `_record_due_fill_interval_or_refuse`, `_settled_account_evidence_bracket`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### external/internal cash classification

No static match; inspect orchestration body and downstream canonical modules.

### target reprojection

`_execute_current_paper_plan`, `_finalize_due_succeeded_cycle_or_refuse`, `_post_projection_action_multipliers`, `_target_projection_or_refuse`, `recover_automated_paper_cycle`

### execution readiness

`ExecutionResult`, `_execute_current_paper_plan`, `_validate_automation_grant`

### execution authority checks

`PaperActivationRefused`, `PreOpenShareUnitAuthorityUnavailable`, `_account_endpoint_lag_is_live`, `_assert_concordance_witness_authority`, `_assert_plan_authorities`, `_broker_cash_state_or_refuse`, `_cash_authority_or_refuse`, `_dual_mutation_observation_or_refuse`, `_execute_current_paper_plan`, `_finalize_due_succeeded_cycle_or_refuse`, `_fresh_connection_factory`, `_guard_broker`, `_informational_active_symbols`, `_inspection_account_or_refuse`, `_instrument_map`, `_preopen_active_security_ids`, `_preopen_views_or_none`, `_provably_clean_empty_noop`, `_record_due_close_nav_or_refuse`, `_record_due_fill_interval_or_refuse`, `_revalidate_preopen_authority_or_refuse`, `_target_projection_or_refuse`, `_validate_automation_grant`, `_validate_broker_grant`, `current_paper_plan`, `execute_automated_paper_plan`, `execute_paper_plan`, `inspect_paper_account`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### command execution

`ExecutionResult`, `PaperAccountInspection`, `_account_endpoint_lag_is_live`, `_action_lookup`, `_execute_current_paper_plan`, `_load_marks_and_tickers`, `_validate_automation_grant`, `_validate_broker_grant`, `current_paper_plan`, `execute_automated_paper_plan`, `execute_paper_plan`, `inspect_paper_account`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### execution result handling

`ExecutionResult`, `PaperAccountInspection`, `_account_endpoint_lag_is_live`, `_cash_authority_or_refuse`, `_observation_economics`, `_target_action_lookup`

### trial evidence

`_default_paper_strategy`, `_execute_current_paper_plan`, `_finalize_due_succeeded_cycle_or_refuse`, `_record_due_close_nav_or_refuse`, `_record_due_fill_interval_or_refuse`, `current_paper_plan`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### prior-cycle finalization

`_finalize_due_succeeded_cycle_or_refuse`, `prepare_paper_plan`

### automation grant validation

`_execute_current_paper_plan`, `_finalize_due_succeeded_cycle_or_refuse`, `_validate_automation_grant`, `_validate_broker_grant`, `execute_automated_paper_plan`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### cycle/session validation

`ExecutionResult`, `PreparationResult`, `_account_endpoint_lag_is_live`, `_action_lookup`, `_assert_concordance_witness_authority`, `_assert_plan_authorities`, `_cash_authority_or_refuse`, `_default_paper_strategy`, `_dual_mutation_observation_or_refuse`, `_execute_current_paper_plan`, `_execution_observation_time`, `_execution_window_or_refuse`, `_finalize_due_succeeded_cycle_or_refuse`, `_fresh_warmed_state`, `_instrument_map`, `_load_marks_and_tickers`, `_missed_sessions`, `_official_preopen_cutoff`, `_post_projection_action_multipliers`, `_readiness_or_refuse`, `_record_due_close_nav_or_refuse`, `_record_due_fill_interval_or_refuse`, `_state_and_plan_or_refuse`, `_target_action_lookup`, `_target_action_multipliers`, `_target_projection_or_refuse`, `_validate_automation_grant`, `_validate_broker_grant`, `build_security_resolver`, `current_paper_plan`, `execute_paper_plan`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### database reads/writes

`_account_endpoint_lag_is_live`, `_action_lookup`, `_load_marks_and_tickers`, `inspect_paper_account`

### transaction ownership

`_account_endpoint_lag_is_live`, `prepare_paper_plan`

### failure classification

`ExecutionResult`, `PaperAccountInspection`, `PaperActivationRefused`, `PaperRetryableRefused`, `PreOpenShareUnitAuthorityUnavailable`, `_account_endpoint_lag_is_live`, `_account_or_refuse`, `_assert_concordance_witness_authority`, `_assert_deterministic_plan_id`, `_assert_plan_authorities`, `_broker_cash_state_or_refuse`, `_cash_authority_or_refuse`, `_clean_or_refuse`, `_default_paper_strategy`, `_dual_mutation_observation_or_refuse`, `_execute_current_paper_plan`, `_execution_window_or_refuse`, `_finalize_due_succeeded_cycle_or_refuse`, `_fresh_connection_factory`, `_fresh_warmed_state`, `_informational_active_symbols`, `_inspection_account_or_refuse`, `_instrument_map`, `_missed_sessions`, `_preopen_views_or_none`, `_provably_clean_empty_noop`, `_readiness_or_refuse`, `_record_due_close_nav_or_refuse`, `_record_due_fill_interval_or_refuse`, `_recovery_account_identity_or_refuse`, `_require_certified_paper_broker`, `_revalidate_preopen_authority_or_refuse`, `_settled_account_evidence_bracket`, `_state_and_plan_or_refuse`, `_target_projection_or_refuse`, `_validate_automation_grant`, `_validate_broker_grant`, `current_paper_plan`, `execute_paper_plan`, `inspect_paper_account`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### retry/restart behavior

`PaperRetryableRefused`, `_account_endpoint_lag_is_live`, `_account_or_refuse`, `_broker_cash_state_or_refuse`, `_cash_authority_or_refuse`, `_clean_or_refuse`, `_default_paper_strategy`, `_dual_mutation_observation_or_refuse`, `_execute_current_paper_plan`, `_execution_window_or_refuse`, `_finalize_due_succeeded_cycle_or_refuse`, `_instrument_map`, `_preopen_active_security_ids`, `_readiness_or_refuse`, `_record_due_close_nav_or_refuse`, `_record_due_fill_interval_or_refuse`, `_recovery_account_identity_or_refuse`, `_settled_account_evidence_bracket`, `_target_projection_or_refuse`, `_validate_automation_grant`, `_validate_broker_grant`, `current_paper_plan`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### machine-readable result construction

`ExecutionResult`, `PaperAccountInspection`, `PreparationResult`, `_account_endpoint_lag_is_live`, `_clean_or_refuse`, `_dual_mutation_observation_or_refuse`, `_execute_current_paper_plan`, `_guard_broker`, `_post_projection_action_multipliers`, `_settled_account_evidence_bracket`, `_target_action_multipliers`, `_target_projection_or_refuse`, `_validate_broker_grant`, `current_paper_plan`, `execute_automated_paper_plan`, `execute_paper_plan`, `prepare_paper_plan`, `recover_automated_paper_cycle`

### cross-module helper functions

`_account_economics`, `_account_endpoint_lag_is_live`, `_account_evidence_is_quiescent`, `_account_or_refuse`, `_action_lookup`, `_assert_concordance_witness_authority`, `_assert_deterministic_plan_id`, `_assert_plan_authorities`, `_broker_cash_state_or_refuse`, `_cash_authority_or_refuse`, `_clean_or_refuse`, `_default_paper_strategy`, `_dual_mutation_observation_or_refuse`, `_execute_current_paper_plan`, `_execution_observation_time`, `_execution_window_or_refuse`, `_finalize_due_succeeded_cycle_or_refuse`, `_fresh_connection_factory`, `_fresh_warmed_state`, `_guard_broker`, `_hash`, `_informational_active_symbols`, `_inspection_account_or_refuse`, `_instrument_map`, `_load_marks_and_tickers`, `_missed_sessions`, `_observation_economics`, `_official_preopen_cutoff`, `_plan_deltas`, `_post_projection_action_multipliers`, `_preopen_active_security_ids`, `_preopen_views_or_none`, `_provably_clean_empty_noop`, `_readiness_or_refuse`, `_record_due_close_nav_or_refuse`, `_record_due_fill_interval_or_refuse`, `_recovery_account_identity_or_refuse`, `_require_certified_paper_broker`, `_revalidate_preopen_authority_or_refuse`, `_settled_account_evidence_bracket`, `_state_and_plan_or_refuse`, `_target_action_lookup`, `_target_action_multipliers`, `_target_projection_or_refuse`, `_validate_automation_grant`, `_validate_broker_grant`

### test-only seams

`_execute_current_paper_plan`, `_execution_observation_time`, `_provably_clean_empty_noop`, `_readiness_or_refuse`, `_require_certified_paper_broker`, `_state_and_plan_or_refuse`, `_validate_broker_grant`, `current_paper_plan`, `prepare_paper_plan`, `recover_automated_paper_cycle`

## Repository consumers and direct seams

### `docs/decisions/paper-lifecycle-decomposition.md`

- L5: `**Behavioral source:** `sentinel/paper.py` at SHA-256`
- L10: `Replace the 3,202-line `sentinel/paper.py` module with a statically readable`
- L11: ``sentinel.paper` package. Every paper-trading lifecycle rule retains one`
- L14: `inputs, economic outputs, and public `sentinel.paper` entry points.`
- L249: ``import sentinel.paper` remains valid. The package initializer explicitly`
- L289: ``sentinel/paper.py` is deleted after the package compiles and the compatibility`

### `docs/sentinel-deployment.md`

- L67: `Alpaca paper. No real money, and **real-money concerns stay off the critical`

### `docs/sentinel-execution-contract.md`

- L48: `sentinel/paper.py                    read-only preparation + strict execution gate`
- L94: `schema                         sentinel.paper_execution_authority/1`

### `docs/sentinel-paper-activation.md`

- L265: ``sentinel.paper_execution_authority/1` certificate whose exact retained`

### `docs/sentinel-paper-observation.md`

- L36: `verdict accepted by `sentinel.paper_execution_certificate/1`, the historical`

### `docs/sentinel-stage-1-production-state.md`

- L30: `* `sentinel/paper.py` — paper-only preparation, durable current-plan`

### `docs/sentinel-stage-4-automation.md`

- L421: ``sentinel.paper_execution_certificate/1` envelope signed offline with Ed25519.`

### `sentinel/_main_impl.py`

- L372: `"schema": "sentinel.paper-observation-warmup-comparison/1",`
- L1012: `paper.PaperActivationRefused,`
- L1053: `from sentinel import paper`
- L1074: `resolve_security_id = paper.build_security_resolver(conn, as_of)`
- L1081: `result = await paper.inspect_paper_account(`
- L1113: `resolver = paper.build_security_resolver(conn, as_of)`
- L1152: `resolver = paper.build_security_resolver(conn, as_of)`
- L1188: `from sentinel import paper, schema`
- L1200: `resolve_security_id = paper.build_security_resolver(conn, args.through)`
- L1206: `raise paper.PaperActivationRefused(`
- L1211: `raise paper.PaperActivationRefused(`
- L1218: `result = await paper.prepare_paper_plan(`
- L1233: `from sentinel import paper, schema`
- L1258: `result = paper.current_paper_plan(`
- L1272: `from sentinel import paper, schema`
- L1283: `resolve_security_id = paper.build_security_resolver(`
- L1287: `result = await paper.execute_paper_plan(`

### `sentinel/administrative_authority.py`

- L82: `"schema": "sentinel.paper-administrative-config/1",`

### `sentinel/authority.py`

- L30: `ACTIVATION_PROFILE_SCHEMA = "sentinel.paper_execution_authority/1"`
- L32: `SIGNED_CERTIFICATE_SCHEMA = "sentinel.paper_execution_certificate/1"`
- L33: `OBSERVATION_CERTIFICATE_SCHEMA = "sentinel.paper_observation_certificate/1"`
- L34: `EMPTY_ACCOUNT_CERTIFICATE_SCHEMA = "sentinel.paper_empty_account_certificate/1"`
- L232: `"schema": "sentinel.paper-execution-config/1",`
- L701: `if evidence["schema"] != "sentinel.paper-observation-evidence/1":`
- L780: `if evidence["schema"] != "sentinel.paper-empty-account-evidence/1":`

### `sentinel/automation_recovery.py`

- L113: `raise paper.PaperRetryableRefused(str(exc)) from exc`
- L149: `raise paper.PaperRetryableRefused(str(exc)) from exc`
- L180: `raise paper.PaperRetryableRefused(`
- L193: `raise paper.PaperRetryableRefused(`

### `sentinel/automation_runtime.py`

- L366: `resolver = paper.build_security_resolver(conn, session)`
- L384: `raise paper.PaperRetryableRefused(str(exc)) from exc`
- L417: `raise paper.PaperRetryableRefused(`
- L549: `result = await paper.prepare_paper_plan(`
- L564: `except paper.PaperRetryableRefused:`
- L567: `paper.PaperActivationRefused) as exc:`
- L598: `result = await paper.recover_automated_paper_cycle(`
- L611: `except paper.PreOpenShareUnitAuthorityUnavailable as exc:`
- L625: `except paper.PaperRetryableRefused:`
- L628: `paper.PaperActivationRefused) as exc:`
- L794: `result = await paper.execute_automated_paper_plan(`
- L807: `except paper.PreOpenShareUnitAuthorityUnavailable as exc:`
- L821: `except paper.PaperRetryableRefused:`
- L824: `paper.PaperActivationRefused) as exc:`

### `sentinel/core/decision.py`

- L78: `"sentinel.paper",`

### `sentinel/empty_account.py`

- L105: `paper._inspection_account_or_refuse(snapshot, expected_account)`
- L106: `inspection = paper.PaperAccountInspection(`
- L132: `expected_account: str) -> paper.PaperAccountInspection:`
- L140: `paper._inspection_account_or_refuse(account, expected_account)`
- L141: `return paper.PaperAccountInspection(`

### `sentinel/empty_account_authority.py`

- L149: `"schema": "sentinel.paper-empty-account-evidence/1",`
- L182: `"schema": "sentinel.paper-empty-account-evidence/1",`
- L189: `"schema": "sentinel.paper-empty-account-candidate/1",`

### `sentinel/observation_authority.py`

- L53: `"schema": "sentinel.paper-observation-accepted-boundary/1",`
- L179: `"schema": "sentinel.paper-observation-warmup/1",`
- L321: `"schema": "sentinel.paper-observation-evidence/1",`
- L360: `"schema": "sentinel.paper-observation-evidence/1",`
- L369: `"schema": "sentinel.paper-observation-candidate/1",`

### `tests/sentinel/test_administrative_authority.py`

- L436: `from sentinel import paper`
- L444: `paper._require_certified_paper_broker(wrapped)  # noqa: SLF001`

### `tests/sentinel/test_automation_deployment.py`

- L155: `"sentinel.paper",`

### `tests/sentinel/test_automation_runtime.py`

- L404: `return paper.PreparationResult(`
- L465: `return paper.ExecutionResult(`
- L546: `return paper.ExecutionResult(`
- L720: `return paper.ExecutionResult(`
- L749: `return paper.ExecutionResult(`
- L780: `return paper.ExecutionResult(`
- L809: `return paper.ExecutionResult(`
- L971: `refusal = (paper.PaperRetryableRefused("settlement pending")`
- L973: `else paper.PaperActivationRefused("plan identity corrupt"))`
- L980: `expected = (paper.PaperRetryableRefused if retryable`
- L998: `raise paper.PreOpenShareUnitAuthorityUnavailable(`
- L1027: `raise paper.PreOpenShareUnitAuthorityUnavailable(`
- L1075: `_control, validated = paper._validate_automation_grant(  # noqa: SLF001`
- L1081: `with pytest.raises(paper.PaperActivationRefused, match="read-only recovery"):`
- L1082: `paper._validate_automation_grant(conn, executable)  # noqa: SLF001`
- L1437: `return paper.ExecutionResult(`
- L1465: `paper._recovery_account_identity_or_refuse(  # noqa: SLF001`
- L1472: `with pytest.raises(paper.PaperRetryableRefused, match="not ACTIVE"):`
- L1473: `paper._account_or_refuse(  # noqa: SLF001`

### `tests/sentinel/test_dual_regenesis_automation_scope.py`

- L157: `paper.PaperRetryableRefused,`
- L180: `paper.PaperRetryableRefused,`

### `tests/sentinel/test_empty_account_binding.py`

- L138: `"schema": "sentinel.paper-empty-account-evidence/1",`
- L221: `"schema": "sentinel.paper-empty-account-evidence/1",`
- L236: `"schema": "sentinel.paper-empty-account-evidence/1",`
- L240: `"schema": "sentinel.paper-empty-account-candidate/1",`
- L555: `warmup={"schema": "sentinel.paper-observation-warmup/1"},`

### `tests/sentinel/test_forward_chain_certification.py`

- L557: `forbidden = ("sentinel.execution", "sentinel.paper", "alpaca")`

### `tests/sentinel/test_informational_paper_mirror.py`

- L242: `paper.PaperActivationRefused,`
- L244: `paper._dual_mutation_observation_or_refuse(  # noqa: SLF001`
- L247: `with pytest.raises(paper.PaperRetryableRefused):`
- L248: `paper._dual_mutation_observation_or_refuse(  # noqa: SLF001`

### `tests/sentinel/test_issue209_simplified_ldrc_runtime.py`

- L1: `from sentinel import paper`
- L9: `config, identity = paper._default_paper_strategy()  # noqa: SLF001`
- L32: `source = open(paper.__file__, encoding="utf-8").read()`

### `tests/sentinel/test_issue209_target_reprojection.py`

- L7: `from sentinel import paper`
- L180: `assert paper._target_action_multipliers(  # noqa: SLF001`

### `tests/sentinel/test_issue223_bil_evidence.py`

- L216: `marks, tickers = paper._load_marks_and_tickers(  # noqa: SLF001`
- L444: `monkeypatch.setattr(paper.journal, "load_commands", lambda *_: [])`
- L446: `paper.reconciliation, "expected_book_from_commands", lambda *_args, **_kw: {})`
- L455: `with pytest.raises(paper.PaperActivationRefused, match="corporate action"):`
- L456: `paper._target_projection_or_refuse(  # noqa: SLF001`

### `tests/sentinel/test_outage_regenesis_integration.py`

- L184: `paper.PaperRetryableRefused,`

### `tests/sentinel/test_paper_activation.py`

- L184: `paper.system_identity, "rehearsal_identity",`
- L208: `paper.readiness, "check_readiness",`
- L211: `paper.feed_store, "latest_visible_session", lambda _conn: frontier)`
- L213: `paper.calendar, "latest_closed_session",`
- L216: `paper.calendar, "sessions_in_range",`
- L221: `paper.calendar, "next_session",`
- L289: `sentinel_transition_hash=paper._hash(state.last_decision),  # noqa: SLF001`
- L290: `strategy_fingerprint=paper._hash(state.strategy_identity),  # noqa: SLF001`
- L350: `return asyncio.run(paper.prepare_paper_plan(**kwargs))`
- L358: `state, current, _cursor = paper._state_and_plan_or_refuse(  # noqa: SLF001`
- L361: `actions = paper._action_lookup(  # noqa: SLF001`
- L364: `active = paper._preopen_active_security_ids(  # noqa: SLF001`
- L394: `cutoff = paper._official_preopen_cutoff(current)  # noqa: SLF001`
- L415: `return asyncio.run(paper.execute_paper_plan(**kwargs))`
- L441: `result = asyncio.run(paper.inspect_paper_account(`
- L479: `output = asyncio.run(paper.inspect_paper_account(`
- L514: `output = asyncio.run(paper.inspect_paper_account(`
- L528: `output = asyncio.run(paper.inspect_paper_account(`
- L545: `paper.PaperActivationRefused,`
- L547: `asyncio.run(paper.inspect_paper_account(`
- L559: `paper.PaperActivationRefused,`
- L561: `asyncio.run(paper.inspect_paper_account(`
- L572: `asyncio.run(paper.inspect_paper_account(`
- L584: `asyncio.run(paper.inspect_paper_account(`
- L615: `with pytest.raises(paper.PaperActivationRefused, match=message):`
- L616: `asyncio.run(paper.inspect_paper_account(`
- L743: `paper.calendar, "previous_sessions",`
- L757: `state = paper._fresh_warmed_state(                    # noqa: SLF001`
- L798: `paper.calendar, "previous_sessions",`
- L815: `state = paper._fresh_warmed_state(                    # noqa: SLF001`
- L839: `paper._assert_concordance_witness_authority(  # noqa: SLF001`
- L842: `paper.PaperActivationRefused,`
- L844: `paper._assert_concordance_witness_authority(  # noqa: SLF001`
- L887: `paper.calendar, "previous_sessions", lambda *_: sessions)`
- L898: `paper.PaperActivationRefused,`
- L900: `paper._fresh_warmed_state(                         # noqa: SLF001`
- L917: `config = paper.load_concordance_parent()`
- L920: `real_previous_sessions = paper.calendar.previous_sessions`
- L921: `real_sessions_in_range = paper.calendar.sessions_in_range`
- L987: `paper.calendar, "previous_sessions", exact_previous_sessions)`
- L989: `paper.calendar, "sessions_in_range",`
- L1023: `config = paper.load_concordance_parent()`
- L1085: `paper.calendar, "previous_sessions",`
- L1089: `paper.calendar, "sessions_in_range",`
- L1209: `monkeypatch.setattr(paper.reconciliation, "reconcile", reconcile)`
- L1212: `paper.PaperActivationRefused,`
- L1272: `not monkeypatch ``paper.calendar`` in this falsifier.`
- L1277: `paper.readiness, "check_readiness",`
- L1280: `paper.feed_store, "latest_visible_session",`
- L1285: `tzinfo=ZoneInfo(paper.calendar.EXCHANGE_TZ))`
- L1288: `paper.PaperActivationRefused,`
- L1293: `assert paper.calendar.latest_closed_session(before_close) \`
- L1306: `monkeypatch ``paper.calendar``.`
- L1311: `paper.readiness, "check_readiness",`
- L1314: `paper.feed_store, "latest_visible_session",`
- L1319: `tzinfo=ZoneInfo(paper.calendar.EXCHANGE_TZ))`
- L1330: `assert paper.calendar.latest_closed_session(after_half_day_close) \`
- L1369: `with pytest.raises(paper.PaperActivationRefused, match="account cash"):`
- L1404: `paper._cash_authority_or_refuse(                 # noqa: SLF001`
- L1432: `paper.PaperRetryableRefused,`
- L1434: `paper._cash_authority_or_refuse(  # noqa: SLF001`
- L1444: `paper.PaperActivationRefused, match="fresh account cash") as error:`
- L1445: `paper._cash_authority_or_refuse(  # noqa: SLF001`
- L1450: `assert not isinstance(error.value, paper.PaperRetryableRefused)`
- L1462: `result = paper.reconciliation.ReconciliationResult(`
- L1467: `return paper.reconciliation.ReconciliationResult(`
- L1486: `monkeypatch.setattr(paper.reconciliation, "reconcile", confirmation)`
- L1490: `paper.PaperRetryableRefused,`
- L1492: `asyncio.run(paper._settled_account_evidence_bracket(  # noqa: SLF001`
- L1507: `result = paper.reconciliation.ReconciliationResult(`
- L1512: `return paper.reconciliation.ReconciliationResult(`
- L1536: `monkeypatch.setattr(paper.reconciliation, "reconcile", confirmation)`
- L1541: `paper._settled_account_evidence_bracket(  # noqa: SLF001`
- L1561: `paper.PreOpenShareUnitAuthorityUnavailable,`
- L1606: `return paper.reconciliation.ReconciliationResult(`
- L1615: `paper.reconciliation, "reconcile", adopt_during_reconcile)`
- L1618: `paper.PreOpenShareUnitAuthorityUnavailable,`
- L1681: `paper.PaperActivationRefused,`
- L1706: `sentinel_transition_hash=paper._hash(               # noqa: SLF001`
- L1708: `strategy_fingerprint=paper._hash(                   # noqa: SLF001`
- L1723: `paper.readiness, "check_readiness",`
- L1726: `paper.feed_store, "latest_visible_session",`
- L1731: `tzinfo=ZoneInfo(paper.calendar.EXCHANGE_TZ))`
- L1733: `assert paper.calendar.session_window(HALF_DAY_EFFECTIVE)[1].hour == 13`
- L1735: `paper.PaperActivationRefused,`
- L1749: `with pytest.raises(paper.PaperActivationRefused, match="not today"):`
- L1761: `paper.PaperActivationRefused,`
- L1774: `paper.PaperActivationRefused,`
- L1830: `paper.PaperRetryableRefused,`
- L1852: `with pytest.raises(paper.PaperActivationRefused, match=message):`
- L1880: `with pytest.raises(paper.PaperActivationRefused, match=message):`
- L1944: `paper.PaperActivationRefused,`
- L1965: `paper.PaperActivationRefused,`
- L2007: `full_history = paper._action_lookup(               # noqa: SLF001`
- L2009: `target_history = paper._target_action_lookup(      # noqa: SLF001`
- L2054: `monkeypatch.setattr(paper.reconciliation, "reconcile", reconcile)`
- L2058: `paper.PaperActivationRefused,`
- L2075: `with pytest.raises(paper.PaperActivationRefused, match="publication"):`
- L2112: `paper.PaperActivationRefused,`
- L2114: `paper.current_paper_plan(conn)`
- L2118: `paper.PaperActivationRefused,`
- L2125: `paper.PaperActivationRefused,`
- L2136: `paper.readiness, "check_readiness",`
- L2142: `paper.PaperActivationRefused,`
- L2171: `inspected = asyncio.run(paper.inspect_paper_account(`

### `tests/sentinel/test_paper_cli.py`

- L79: `return paper.ExecutionResult(`
- L114: `return paper.PaperAccountInspection(`
- L188: `paper.PaperActivationRefused("stop after read-only wiring")))`
- L429: `raise paper.PaperActivationRefused("ownership is not established")`
- L733: `paper.PaperActivationRefused,`

### `tests/sentinel/test_paper_close_nav_gate.py`

- L12: `from sentinel import paper, trial, trial_close, trial_fills`
- L96: `with pytest.raises(paper.PaperRetryableRefused, match="not a certified"):`
- L97: `run(paper._record_due_close_nav_or_refuse(  # noqa: SLF001`
- L114: `result = run(paper._record_due_close_nav_or_refuse(  # noqa: SLF001`
- L129: `paper.PaperRetryableRefused, match="temporarily unavailable"):`
- L130: `run(paper._record_due_close_nav_or_refuse(  # noqa: SLF001`
- L141: `paper.PaperActivationRefused, match="malformed or contradictory"):`
- L142: `run(paper._record_due_close_nav_or_refuse(  # noqa: SLF001`
- L155: `paper.PaperActivationRefused, match="acceptance contract"):`
- L156: `run(paper._record_due_close_nav_or_refuse(  # noqa: SLF001`
- L172: `with pytest.raises(paper.PaperRetryableRefused, match="not a certified"):`
- L173: `run(paper._record_due_fill_interval_or_refuse(  # noqa: SLF001`
- L195: `result = run(paper._record_due_fill_interval_or_refuse(  # noqa: SLF001`
- L219: `paper.PaperActivationRefused,`
- L221: `run(paper._record_due_fill_interval_or_refuse(  # noqa: SLF001`
- L231: `(RuntimeError("ledger not final"), paper.PaperRetryableRefused,`
- L234: `paper.PaperActivationRefused, "malformed or contradictory"),`
- L249: `run(paper._record_due_fill_interval_or_refuse(  # noqa: SLF001`
- L275: `with pytest.raises(paper.PaperActivationRefused, match=message):`
- L276: `run(paper._record_due_fill_interval_or_refuse(  # noqa: SLF001`
- L295: `paper.PaperActivationRefused, match="immutable acceptance contract"):`
- L296: `run(paper._record_due_fill_interval_or_refuse(  # noqa: SLF001`
- L324: `with pytest.raises(paper.PaperActivationRefused, match="net=0"):`
- L325: `paper._cash_authority_or_refuse(  # noqa: SLF001`
- L331: `paper._cash_authority_or_refuse(  # noqa: SLF001`
- L362: `paper.PaperActivationRefused, match="activity identity scheme"):`
- L363: `paper._cash_authority_or_refuse(  # noqa: SLF001`
- L422: `paper.target_reprojection, "load_projection",`
- L425: `paper.target_reprojection, "assert_projection",`
- L438: `result = run(paper._finalize_due_succeeded_cycle_or_refuse(  # noqa: SLF001`
- L490: `paper.PaperRetryableRefused,`
- L492: `run(paper._finalize_due_succeeded_cycle_or_refuse(  # noqa: SLF001`
- L528: `raise paper.PaperActivationRefused("due-cycle gate reached")`
- L535: `paper.schema, "require_runtime_schema", lambda _conn: None)`
- L537: `paper.journal, "writer_lock", lambda _conn: nullcontext())`
- L543: `mode=paper.RolloutMode.PINNED_1_00, version=1,`
- L546: `paper.publication, "pinned",`
- L551: `paper.calendar, "latest_closed_session",`
- L554: `paper.feed_store, "latest_visible_session",`
- L563: `monkeypatch.setattr(paper.catchup, "resume_state", lambda _conn: None)`
- L565: `paper.catchup, "last_processed_session", lambda _conn: None)`
- L567: `paper.journal, "latest_plan", lambda _conn: PLAN)`
- L569: `paper.trial, "due_succeeded_cycle_id", lambda *_args, **_kwargs: "old")`
- L576: `paper.journal, "load_commands", lambda *_args, **_kwargs: ())`
- L582: `paper.preopen_authority, "overlay_actions",`
- L587: `monkeypatch.setattr(paper.reconciliation, "reconcile", reconcile)`
- L603: `paper.PaperActivationRefused, match="due-cycle gate reached"):`
- L604: `run(paper.prepare_paper_plan(`
- L647: `paper.PaperActivationRefused, match="cannot be backfilled"):`
- L648: `paper._cash_authority_or_refuse(  # noqa: SLF001`

### `tests/sentinel/test_paper_fresh_connection.py`

- L7: `from sentinel import paper`
- L30: `factory = paper._fresh_connection_factory(_conn(redacted_dsn, "secret"))`
- L43: `with pytest.raises(paper.PaperActivationRefused, match="fresh PostgreSQL"):`
- L44: `paper._fresh_connection_factory(_conn("", "secret"))`

### `tests/sentinel/test_paper_observation_authority.py`

- L182: `"schema": "sentinel.paper-observation-evidence/1",`
- L260: `"schema": "sentinel.paper-observation-warmup/1",`
- L268: `"schema": "sentinel.paper-observation-evidence/1",`
- L285: `"schema": "sentinel.paper-observation-evidence/1",`
- L292: `"schema": "sentinel.paper-observation-candidate/1",`

### `tests/sentinel/test_preopen_paper_gate.py`

- L188: `active = paper._preopen_active_security_ids(  # noqa: SLF001`
- L196: `cutoff = paper._official_preopen_cutoff(plan)  # noqa: SLF001`
- L210: `paper.PreOpenShareUnitAuthorityUnavailable,`
- L212: `paper._revalidate_preopen_authority_or_refuse(  # noqa: SLF001`
- L223: `flat_deltas = paper._plan_deltas(  # noqa: SLF001`
- L226: `assert not paper._provably_clean_empty_noop(  # noqa: SLF001`
- L230: `empty_deltas = paper._plan_deltas(  # noqa: SLF001`
- L233: `assert paper._provably_clean_empty_noop(  # noqa: SLF001`
- L236: `dust_deltas = paper._plan_deltas(  # noqa: SLF001`
- L239: `assert not paper._provably_clean_empty_noop(  # noqa: SLF001`
- L253: `committed_deltas = paper._plan_deltas(  # noqa: SLF001`
- L256: `assert not paper._provably_clean_empty_noop(  # noqa: SLF001`
- L265: `cutoff = paper._official_preopen_cutoff(  # noqa: SLF001`
- L287: `cutoff = paper._official_preopen_cutoff(plan)  # noqa: SLF001`
- L327: `result = asyncio.run(paper.recover_automated_paper_cycle(`
- L328: `conn=object(), broker=broker, base_url="https://paper.example",`
- L361: `paper.target_reprojection, "project_target", lambda *_args, **_kw: fresh)`
- L363: `paper.target_reprojection, "load_projection", lambda *_args, **_kw: stale)`
- L365: `paper.target_reprojection, "assert_projection",`
- L372: `paper.PaperActivationRefused,`
- L374: `paper._target_projection_or_refuse(  # noqa: SLF001`
- L398: `paper.target_reprojection, "project_target",`
- L401: `paper.target_reprojection, "record_projection",`
- L406: `result = paper._target_projection_or_refuse(  # noqa: SLF001`
- L431: `paper.target_reprojection, "project_target",`
- L434: `paper.target_reprojection, "record_projection",`
- L440: `paper.PaperActivationRefused,`
- L442: `paper._target_projection_or_refuse(  # noqa: SLF001`
- L457: `cutoff = paper._official_preopen_cutoff(plan)  # noqa: SLF001`
- L482: `paper.PreOpenShareUnitAuthorityUnavailable,`
- L484: `asyncio.run(paper.recover_automated_paper_cycle(`
- L485: `conn=object(), broker=broker, base_url="https://paper.example",`
- L501: `paper.PreOpenShareUnitAuthorityUnavailable,`
- L503: `asyncio.run(paper.recover_automated_paper_cycle(`
- L504: `conn=object(), broker=broker, base_url="https://paper.example",`
- L522: `result = asyncio.run(paper.recover_automated_paper_cycle(`
- L523: `conn=object(), broker=broker, base_url="https://paper.example",`
- L557: `paper.feed_store, "latest_visible_session",`
- L577: `result = asyncio.run(paper.recover_automated_paper_cycle(`
- L578: `conn=object(), broker=broker, base_url="https://paper.example",`
- L603: `result = asyncio.run(paper.recover_automated_paper_cycle(`
- L604: `conn=object(), broker=broker, base_url="https://paper.example",`

### `tests/sentinel/test_production_decision.py`

- L447: `"sentinel.paper",`

### `tests/sentinel/test_runtime_regressions_137_148_149_150.py`

- L94: `monkeypatch.setattr(paper.publication, "require_current",`
- L96: `monkeypatch.setattr(paper.feed_store, "latest_visible_session",`
- L101: `monkeypatch.setattr(paper.calendar, "latest_closed_session",`
- L107: `paper._validate_broker_grant(`

### `tests/sentinel/test_shadow_observation.py`

- L1686: `name == "sentinel.paper"`

### `tools/sentinel_empty_account_authority.py`

- L35: `!= "sentinel.paper-empty-account-candidate/1"`
- L47: `!= "sentinel.paper-empty-account-evidence/1"`

### `tools/sentinel_observation_authority.py`

- L44: `!= "sentinel.paper-observation-candidate/1"`
- L56: `!= "sentinel.paper-observation-evidence/1"):`
- L84: `or warmup.get("schema") != "sentinel.paper-observation-warmup/1"`

### `tools/step4_paper_lifecycle_inventory.py`

- L2: `"""Generate the Step 4 responsibility and dependency map for sentinel.paper.`
- L18: `SOURCE_PATH = ROOT / "sentinel" / "paper.py"`
- L209: `"from sentinel import paper",`
- L210: `"from sentinel.paper import",`
- L211: `"import sentinel.paper",`
- L212: `"sentinel.paper",`
- L213: `"paper.",`
- L339: `"Generated from the exact `sentinel/paper.py` source on the Step 4 base.",`

## Transaction and ordering review rule

Every moved definition retains its original body, exception types, call ordering, and connection ownership. The decomposition must preserve the production sequence discovered through the root call graph and must leave canonical execution, feed, strategy, authority, persistence, and Wealth Core implementations unchanged.
