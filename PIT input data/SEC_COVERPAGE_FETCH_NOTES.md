# SEC cover-page evidence gate

This retrieval stage is intentionally conservative.

A previously unresolved Orion buy is counted as newly security-type-covered only when a historical SEC filing dated strictly before the buy contains both:

1. the exact Orion ticker symbol, and
2. a positive common/ordinary-equity security title.

Preferred stock, warrants, options, RSUs, phantom stock and convertible instruments are not positive common-stock evidence. Current SEC ticker maps and Sharadar `secfilings` values may be used only as retrieval hints to locate a CIK; they are never themselves PIT classification evidence. Unresolved cases remain unknown/ineligible.
