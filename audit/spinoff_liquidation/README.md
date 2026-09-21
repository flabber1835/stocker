# Held spin-off economic certificate

This certificate exercises the new held spin-off transition against the actual
June 30, 2015 economic-replay checkpoint. It is a narrow economic test, not a
production continuation or broker-settlement claim.

Baxter held 105 shares immediately before its July 1, 2015 separation of
Baxalta. The reviewed terms deliver one BXLT share for each BAX share. The
retained input has a July 1 BXLT raw open of USD 31.90 and a BAX raw open of
USD 37.55. The independent oracle is therefore:

```text
child shares       = 105 * 1 = 105
gross child value  = 105 * 31.90 = 3,349.50
net sale proceeds  = 3,349.50 * (1 - 0.001) = 3,346.1505
reference scale    = 37.55 / (37.55 + 31.90)
                   = 0.5406767458603312
```

The production transition matched the oracle, retained all 105 BAX shares,
posted distinct child-receipt and child-liquidation ledger events, and did not
set a BAX exit. The peak changed from 77.0 to 41.6321094312455; removing this
rebase makes the focused falsifier fail and would leave the mechanical
post-distribution drawdown in the stop state.

The resulting July 1 controlled-account NAV is USD
350,902.5474701088548486692719. This one-session result establishes the
accounting behavior at the blocker. It does not state the eventual twenty-year
performance and does not authorize bypassing the replay's source/checkpoint
binding when continuation moves to the revised kernel.

Terms source:
https://www.sec.gov/Archives/edgar/data/10456/000119312515246136/d57625d8k.htm

Exact inputs, source hashes and observed outputs are retained in
`certificate.json`.
