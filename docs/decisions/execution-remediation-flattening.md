# Execution remediation flattening

Status: accepted for implementation
Date: 2026-08-28
Base: `0f47e3d4208c1af9a7884804ff6683669b9d53ee`

## Decision

The certified execution behavior remains unchanged, but its implementation will be moved from import-time remediation layers into the canonical modules that own each contract.

The target ownership is:

- `sentinel/execution/alpaca.py` owns the complete Alpaca transport and observation semantics as one module and one global namespace.
- `sentinel/execution/guarded.py` owns the complete guarded broker membrane.
- `sentinel/execution/journal.py` owns durable command, observation, fill, and terminal-recovery persistence semantics.
- `sentinel/execution/reconcile.py` owns reconciliation comparisons and broker-evidence conflict detection.
- `sentinel/execution/authority_gate.py` owns the execution read/mutation operation policy.
- `sentinel/execution/broker_cash.py` owns the accepted broker cash-activity taxonomy.
- `sentinel/execution/executor.py` owns exposure-increase fences and their registry.

No portfolio intent, command identity, UNKNOWN-state handling, account binding, cash accounting, recovery boundary, asset-id authority, paper-only restriction, or exposure-increase fence changes in this refactor.

## Migration rule

Flattening proceeds in behavior-preserving slices. Each slice must remove a runtime mutation only after the equivalent behavior exists in the canonical owner and its existing falsifiers pass.

The first slice removes the self-cancelling emergency-authority serialization overlay. Current `alpaca_remediation.install_automation_serialization()` temporarily wraps kill/revocation operations with the execution writer lock, while `alpaca_remediation_authority_semantics.install()` immediately recovers and restores the original non-blocking functions. The certified net behavior is therefore the original immediate kill/revocation semantics. That net behavior becomes direct again: no temporary wrapper and no restoration layer.

The Alpaca transport and hardened adapter remain in the same canonical module. Paging bounds, time capture, paper-endpoint enforcement, and other transport constants are runtime/test seams of that adapter and must resolve from the same module globals as the methods that consume them.

Subsequent slices move the remaining journal, reconciliation, cash-classification, compatibility, and restore-fence behavior into their canonical modules. The legacy remediation modules are deleted only after their last effective behavior has moved.

## Safety invariants

1. `engage_kill`, certificate revocation, key revocation, and system-certificate revocation remain immediate database fencing operations and never wait for a broker send already past the durable `SEND_PENDING` boundary.
2. A request that crossed `SEND_PENDING` keeps its deterministic client key and is recovered through normal command reconciliation.
3. Import order must not change execution semantics.
4. Production and test adapters retain their existing capability distinctions.
5. The PR must preserve the existing execution and automation targeted test surfaces; no golden or economic fixture is re-pinned.

## Completion criterion

The execution package has one statically readable implementation path for each financial/safety rule, and `sentinel/execution/__init__.py` no longer installs remediation overlays to construct production behavior.