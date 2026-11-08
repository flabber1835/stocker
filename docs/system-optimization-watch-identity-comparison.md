# Bound predecessor input identities in reference comparison

The strict existing watch comparator refused two B/B0 rows after the completed
reference exports were authenticated. The preserved exact mismatch is only
`$.predecessor_input_sha256`, at watch indexes1 and33. P00 shares B's values.
No new exclusion is admitted from the shape or length of a hash alone.

Keep the existing comparator unchanged. A separate explicit bound comparison
first verifies each differing watch row against its actual authenticated own
predecessor checkpoint: inner checkpoint, state hash, input hash and exact date.
It also verifies the exact archived overlay file SHA and compares its complete
document against the other arm, excluding only its predecessor checkpoint key.
The predecessor bases must match. Only then remove the two predecessor-input
identity fields from temporary comparison copies and call the strict comparator.
No saved checkpoint, journal or event is edited. Any missing preimage, changed
date, changed economic field or changed fact document refuses the comparison.
The original strict refusal and original full journal hashes remain retained.

This does not relax financial row equality. Every formation/daily state hash,
every economic evidence field, all monthly values and complete final state must
still match. Canonical restores and every historical prefix were independently
reviewed on hosted compute; the read-only comparison does not replay finance.
