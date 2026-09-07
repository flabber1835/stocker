# Dividend settlement semantic tombstone

Authoritative Production-equivalent Champion dividend settlement lag: **1 trading session**.

The 15-session implementation is obsolete and must never certify. Historical artifacts that
executed `book.receivables.append((gday+15,...))`, including run 34064302990, are retained only
as historical evidence and are not valid baselines for the intended Production-equivalent economics.

Certification must structurally parse the unique receivable due-session expression and prove it is
exactly `gday + 1`. Substring checks such as searching for `gday+1` are prohibited because they also
match `gday+15`.
