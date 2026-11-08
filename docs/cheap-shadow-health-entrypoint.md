# Cheap shadow health entrypoint

Decision, 2026-11-08, before implementation. The existing canonical signed health
predicate is already calendar-free, but the deployed `python -m
sentinel.shadow_supervisor --health` imports recovery/service/runtime and the
worker before checking even an absent heartbeat. On exact 29ff source a private
0.5 CPU / 1 GiB negative CLI took 4.969 s / 2.295 CPU seconds initially and
2.041 s / 0.973 CPU seconds in a second fresh Python process. Its trace loaded
435 modules, including
shadow_recovery/runtime and the worker; no pandas/numpy/exchange_calendars loaded.
The earlier calendar fix worked, but the entrypoint bootstrap remained broad.

Extract the identical frozen ShadowServiceConfig, three exception definitions,
observation/SHA regexes and forbidden broker env tuple into one lightweight
`shadow_service_config` module. Preserve every field, default, validation order,
Decimal rule, error message and operational/legacy forbidden mode. Import the
existing `feed.observation_timing.POLICY`, replacing only the two references to
shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY (which is already exactly that
canonical POLICY alias). Do not copy its literal or create another validator.
shadow_service reexports the same objects/private constants; existing recovery
aliases through base remain identical. Do not change shadow_runtime or timing.

Extract the five unchanged literal worker exit codes into one lightweight
`shadow_exit_codes` module. Worker reexports them and supervisor consumes
that shared protocol without importing worker financial composition. Supervisor
imports config/exceptions from the lightweight module and keeps a lazy public
service_health forwarding patchpoint. Only actual missing/legacy projection
fallback imports the original recovery implementation. Preserve its signature,
typed results/exceptions and the original 3 s parent dependency deadline.

Keep the existing `_health_snapshot`, `_health`, CLI options, heartbeat/pending/
critical semantics and signed projection classifier shared. A valid health
projection must avoid recovery/service/runtime/worker bootstrap. Missing or
malformed evidence still fails closed or follows its exact existing fallback;
there is no new positive cache, copied health predicate or wider deadline.

Economic manifest SHA256
`8d79b1fd21465491d5208c3d415a4e360b98e6f6d82c3a2bb01024c57c04645b`
recursively contains none of the moved service/recovery/supervisor/worker modules.
shadow_runtime occurs only in predecessor_files; observation_timing remains an
unchanged operational SOURCE_GUARD/dependency reference. No economic manifest,
frozen contributor, calendar, execution, schema or source profile is changed.
The complete actual runtime source closure still requires ordinary sealing.

Pin the original normalized AST of config/errors/env guards, permitting only
the canonical policy reference substitution; test exact shared aliases, original
exit literals, config byte equivalence, and guard/code mutation falsifiers.
Run actual fresh CLI import guards and valid-projection health with financial
bootstrap forbidden, plus fallback/pending/critical/stale cases and the original
service/supervisor/calendar tests. Compare candidate cold metadata under the
same private 0.5 CPU / 1 GiB bounds; report timings without machine-sensitive gates.
Canonical worker/source qualification after sealing remains the installer's
separate required check. Do not run the full suite or Wealth Core tests.

Earlier consumer tests exercised Projection/_temporal_health directly, and other
tests preloaded service/runtime at module scope. Those tests correctly protected
calendar eligibility but did not execute the deployed CLI bootstrap. New tests
cover the entrypoint and the unchanged predicate separately.

The moved dataclass's defining module changes, but legacy public aliases must
still resolve old lookups and all isinstance/except checks. Config hashing uses
the unchanged dataclass fields/asdict and same environment, not the defining
module. No cross-image pickle transport or persisted financial schema changes.
Broader automation bootstrap and publisher cadence designs remain separate work.
