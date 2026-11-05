# P01 final-session ORLA input correction

Design recorded before implementation. P01's admitted financial predecessor now
contains 2,155 sessions through 2026-07-30. Its descriptor SHA256 is
`d5bfb93d098f9c45dd18697463f152a54c77df2b6fb23c987f1c418556a2c176`.
The corrected AMWD attempt passed new-event qualification, financial execution,
hosted stopped review and independent DATA review for 44 new sessions. The sole
remaining session, 2026-07-31, refused an unresolved native ORLA cash-merger marker.
No July 31 financial transition or unsent tail is admitted.

The retained source identity is ORLA `622077003929363486`; EQX is
`18397188588917778`, issuer `SID:18397188588917778`. The native terminal preimage
hash is `38af459b36abb7bbd88339f114ac17c3755db5be8836982edd3077f36e8b65da`.
The native `deal_value_musd=3265.6` is not a per-share cash price.

The [July 28 court-approval release](https://www.sec.gov/Archives/edgar/data/1680056/000127956926000709/ex991.htm)
specifies one Equinox Gold share and US$0.0001 for each Orla share. The
[July 31 closing release](https://www.sec.gov/Archives/edgar/data/1680056/000127956926000721/ex991.htm)
confirms closing; the [exchange notice](https://www.sec.gov/Archives/edgar/data/1143313/000114331326000045/ruleprovisionnotice.htm)
confirms the conversion and suspension on July 31. Retain that source calendar.

Add one typed, literal-bound future input in the existing P01 continuation
driver. Compile only the exact unresolved ORLA terminal into a native-enum
conversion with ratio `1.00`, EQX delivery identity and cash component `0.0001`.
Use the canonical native number representation. Do not omit the nominal cash or
replace the package with an aggregate deal value. Preserve every unrelated field.

This correction supports never-held ORLA only. Prove absence from the whole
admitted book, slots, pending intents, receivables, ownership ledger and terminal
claims before adoption and before use. Prove the actual transition introduces no
ORLA cash, shares or claim. Held settlement, holder-cent rounding and fractional
cash pricing remain unsupported. Preserve all 16 admitted inputs, original
source epoch, financial state and journal prefixes; canonical input-zero adoption
must change no financial state.

There is exactly one remaining frozen session. Qualify that one session in a
fresh REFERENCE branch and a fresh FAST branch, compare their complete canonical
runtime checkpoints and outcomes, then execute a separate fresh financial branch
from the admitted predecessor and require complete equality to qualification.
No qualification state is adopted. This one-session qualification is permitted
only for the exact 2,155-session July 30 predecessor, July 31 endpoint and this
new input. Every other new-event qualification retains two sessions. Do not
extend the source axis or replay an admitted session to manufacture a second.

Keep existing worker resources, deadlines, stopped/UNKNOWN handling, encryption
and independent review/root admission gates. Reuse the existing workflow, driver,
codecs and readers. Publish no final metrics until all 2,156 sessions and the
final monthly report pass independent review and root admission. Core selection
still precedes Sentinel tuning; no PAPER, broker or canonical engine change.
