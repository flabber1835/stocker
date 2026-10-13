# Alpaca listing identity and execution permission

Decision: 2026-10-12. Operational source policy
`sentinel.alpaca-openfigi-operational-source/3` separates listed market-data
membership from Alpaca's current permission to trade an asset.

Two fenced GO attempts on certified commit `9f9d5b08` refused publication at
inventory corroboration. The retained inventories contained 13,202 and 13,207
entries; later GETs changed 55 and 38 filtered entries respectively. A scoped
read-only diagnostic confirmed the disappearing entries remained active US
equities on the same exchange, with the same asset UUID and symbol, while
`tradable` had become false. They had not disappeared from the asset response.
The source's `tradable` filter turned a broker permission change into a market
identity change and repeatedly exhausted work before publication.

Alpaca distinguishes active listing status from trading permission in its
[asset documentation](https://docs.alpaca.markets/us/docs/broker-api-faq).
The repository membrane already assigns broker restrictions, halts and rejects
to execution. They must not select Wealth Core's holdings or Sentinel's exposure.

## Source and execution contract

Current discovery retains active `us_equity` listings outside OTC independently
of `tradable`, including when that broker field is false or absent. UUID, symbol,
exchange, uniqueness, OpenFIGI instrument classification, contiguous price
coverage, action economics and protected live anchors remain mandatory.
Inactive assets and OTC listings remain excluded. No ticker-specific exception
or inferred listing continuity is introduced.

Corroboration compares listing identities after acquisition. A broker flag-only
change must leave that comparison unchanged. A true UUID, symbol, exchange or
active-listing change still refuses the candidate and uses the existing bounded
successor path, its original deadline and its restart cap. Provider timestamps,
raw-response hashes and acquisition manifests retain their original meaning;
ignoring a broker field does not make Alpaca an atomic cross-endpoint source.

Execution keeps its fresh asset-metadata check. An asset that Alpaca will not
trade remains refused before plan/order construction. This change grants no
broker permission, disables no guard and creates no autonomous liquidation path.
Wealth Core and Sentinel do not receive the broker flag in their inputs.

## Retained state and qualification

Source versions `/1` and `/2` remain historical input evidence. Their published
bytes and the original canonical book are not rewritten. Fresh readiness must
acquire `/3`; `/2` cannot satisfy it merely because its date is current. The
existing reference `/3` identity bindings and digest checks are required for
source `/2` and `/3`. Unknown source/reference pairings refuse. Inventory clocks
are read under their original source schema without renewing observation age.

The exact retained-book admission adds only `feed/openfigi.py` to the reviewed
close-cycle source scope and pins the verified origin, preceding certified main
and completed target bytes. Unreviewed changes and additions still refuse.

Qualification covers flag-only changes through acquisition/corroboration,
genuine identity/listing changes, inactive/OTC/type exclusions, duplicate identity
refusal, old/new source readers, fresh-policy admission and execution refusal of
untradable assets. A deliberate restoration of the broker flag filter must make
the regression fail. Run actual GET-only provider evidence and an isolated
public-input acquisition/formation/restart rehearsal; never copy the production
database for it or call an unqualified branch image deployed or certified.
The original immutable book and incident history must remain intact. Final
financial GO, semantic restore and prospective cycle recovery are required on
the protected certified installed image before releasing the paper kill fence.
