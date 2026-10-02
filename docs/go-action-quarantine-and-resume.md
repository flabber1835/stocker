# GO action quarantine and retained-part verification

## Decision

The production current-window GO path treats an unusable corporate-action row as a security-scoped uncertainty when its permanent identity and effective session can be resolved unambiguously. It retains the source row, records the reason and identity in publication evidence, and excludes that security from new Wealth Core selections. If the shadow book already holds it, the existing unresolved-action rule must fail closed rather than inventing cash or share quantities. An unresolved identity, a broad/systemic anomaly, or an action affecting a held security without safe resolution still refuses publication. There are no ticker-specific production exceptions.

Quarantine is keyed by permanent security identity rather than display symbol. A later publication carries a prior quarantine until an explicit, separately reviewed resolution; merely rolling the action date out of the 300-session window does not clear it. The source remains Sharadar for production. Alpaca corporate-action responses are diagnostic evidence, not an implicit substitute for an unknown Sharadar amount or ratio. Execution remains the only broker-facing layer.

Detect and classify action anomalies before the full independent price coverage scan. The resulting publication evidence must bind the affected security identities and source-row diagnostics. At most 16 permanent identities may be quarantined per publication; a larger number is treated as a systemic source failure. Preserve all price rows and exact coverage accounting. At the Wealth Core input boundary mark quarantined bars untradeable and unresolved. Neutral split/dividend placeholders on those barred inputs prevent applying an unverified entitlement to an existing holding; they do not certify that no action happened. Raw source evidence and stored canonical bars remain intact.

## Retained acquisition and backup renewal

The first GO acquisition stores per-part manifest identity, row count and content digest. On a non-READY job, resumption checks the manifest and binding immediately but defers the expensive stored-price payload scan. The mandatory independent coverage pass verifies each retained part's row count, key identity and digest while reading those same rows once, before candidate sealing or publication. Reference parts and READY-job resumes keep their immediate verification. A mismatch still refuses the job; a completion marker alone is never proof of retained content.

Backup renewal keeps its restore-horizon and deadline guards. Renewal resumes the same fenced job and does not reacquire completed provider exports. Integrating retained verification into coverage avoids the second full stored-price scan without weakening source integrity.

## Falsifiers and measurement

Tests must show an ordinary security remains eligible, an anomalous security is excluded without a ticker literal, an unresolved identity or systemic anomaly refuses, prior quarantine survives a new publication, and held exposure does not receive invented cash or units. Corrupt a committed retained part and prove that integrated verification refuses before sealing; an intact retained part must avoid the redundant payload pass. Measure partition acquisition, retained verification, coverage, normalization and backup-renewal time separately during a real-data GO rehearsal.
