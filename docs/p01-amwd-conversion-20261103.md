# P01 American Woodmark input correction

The accepted P01 checkpoint is 2,111 financial sessions through May 27, 2026.
Its next frozen input labels AMWD SID `332224216763941431` as a cash merger
with no cash consideration. The canonical guard correctly refuses May 28.
The closing SEC 8-K states that each AMWD share converts into 5.150 MasterBrand
shares, plus cash in lieu of fractions. This is a stock conversion, not cash.

Primary source:
https://www.sec.gov/Archives/edgar/data/794619/000119312526243155/d50625d8k.htm

The retained feed identifies MasterBrand as MBC SID `774426370326168272`,
issuer `SID:774426370326168272`. The admitted state contains no AMWD identity
in Wealth Core, pending intents or the full ledger. Restrict this correction to
that never-held scope. A held case and its unknown fractional cash settlement
remain unsupported and must refuse. Do not invent a fractional price.

Add one typed future input, number sixteen, to the existing P01 continuation
driver. Bind the exact native term, admitted checkpoint/state/source epoch,
source/target identities, event date and the contractual decimal ratio. Compile
only this one native terminal to the existing canonical `CONVERSION` carrier.
Keep its ratio as the exact string `5.150`, its cash and fractional-price fields
absent, and its holder aggregation unchanged. Preserve every unrelated terminal,
spin-off, bar and packet field. Reject another same-session action involving
AMWD, an unregistered document, wrong native preimage or a changed parent.

Hydrate all fifteen prior inputs unchanged before restore and register the new
document through the existing canonical future-input adoption. That adoption
must leave the whole financial state, cursor and committed session count intact.
Before the event reject AMWD ownership, pending intents, slots/reservations,
receivables, historical ownership and terminal claims. After the transition
require zero source cash/share value and no AMWD holding or claim. MBC's existing
independent holdings and ordinary unrelated session events retain their rules.

Qualify only the two new future sessions in REFERENCE and FAST modes. Require
complete runtime checkpoint equality, full restore equality, and equality of a
fresh financial branch to those two qualification checkpoints. Reuse all closed
prior qualification and financial evidence. Retain the existing lossless journal
representation and two-GiB export bound. Resume exactly the final 45 financial
sessions through July 31; perform the existing hosted stopped review, independent
DATA accounting review and root raw-checkpoint/prefix admission before completion
or CAGR is claimed. A later refusal preserves its actual new prefix.

Use the frozen financial source epoch and existing workflow, codecs, runner,
reporting and export paths. No canonical Core/controller changes, local financial
replay, provider-price query, broker/PAPER/WSL/service change, new automation,
main merge or deployment is authorized by this research continuation.

The first hosted check exposed an adapter type defect: the native terminal kind
is an enum even though its JSON representation is a string. Preserve that enum
type when selecting `CONVERSION`. The original qualification refusal remains
closed evidence; neither branch advanced a financial session. Require the
REFERENCE branch to return two successful components before starting FAST, while
retaining every existing whole-runtime equality check. A failed REFERENCE check
must save its evidence and stop before another expensive startup.
