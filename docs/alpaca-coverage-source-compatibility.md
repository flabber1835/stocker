# Source compatibility for Alpaca event coverage

Retain the exact installed release as a reviewed source predecessor. The
complete Git archive of `2adeda3b18e9323827e9d12e8782034c3ecc3e55` contains 522
Sentinel Python sources with inventory digest
`68afc6c589a3dd86ba57dfcbbbed6704ee67654d07ccc239a8965eb724f27330`.
Its schema-114 source profile has SHA-256
`2c686dc38ad7322f4f80822b39c321d3bab3b1e2e8e6b6a6efdf639c48601408`.
Append this exact predecessor to the existing retained history. Preserve every
earlier entry, the structural baseline, and the comparison behavior for a
missing, extra, or changed file.

After the reviewed application edits are committed, generate the schema-115
candidate with `scripts/sentinel_source_history.py seal`. The generator reads
only the two named Git revisions and refuses if the candidate edits the two
generated inputs. The candidate map covers the complete set of Sentinel Python
sources. Apply the generated checker and catalog together. Verify their exact
source inventory and preceding comparison edges against the untouched Git
archives.

This compatibility edge has `authority_effect=NONE`. It preserves the ability
to read retained evidence while the exact new runtime code has its own identity.
The LIVE and PAPER account authorities, qualification evidence, and deployment
permissions remain separate.
