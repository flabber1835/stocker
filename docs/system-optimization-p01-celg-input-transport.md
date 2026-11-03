# Private captured CELG quote input transport

The CELG bridge needs the already retained Alpaca response and its complete
capture receipt on the hosted qualifier. Public Git contains only source and
hash commitments. The private gzip response and capture JSON remain outside Git.
The transport does not contain a book, checkpoint, journal, financial parent or
new provider request. The separate bridge input document binds the resulting
manifest to its own admitted 475-session predecessor.

Use the existing `research-capital-risk-inputs-20261027` prerelease in
`flabber1835/stocker`. Later Alpaca captures already append encrypted market
inputs to this same approved destination. Root has accepted this reuse. Each new
asset has a name containing its complete ciphertext SHA256; an existing name is
reusable only with identical state, length and digest. Never overwrite, delete or
replace an old asset. Root alone performs cloud publication after reviewing the
concrete prepared package. The module itself has no upload command or credential
discovery capability.

Reuse `local_stage.pack_data` and `seal.EncryptWriter`: AES-256-GCM with fresh
12-byte nonce, authenticated `CRSEAL01` header and full 16-byte tag. Recover only
the existing research key through the existing Windows DPAPI helper for local
preparation. The key remains separate from assets, descriptors, logs, arguments
and offline workers; no new secret or PAPER/provider credential is needed. Pin
the original crypto implementation bytes. Record the original crypto transport
protocol hash `a4591ac1a8ca6d927d4a5452c8bfce766e910fc75d33dbbd48d3f0fd8adb1e52`
and the separate consumer campaign protocol hash
`a5bacaa1bc51bb5ac376b5163186208aeb4d3aedd130fa7ccdb5e54058cb26d3`.
Do not substitute one namespace for the other.

The new, bounded capsule has a first versioned manifest and exactly two regular
files: `quote.json.gz` and `capture.json`. Commit the whole retained compressed
response, decompressed raw response and capture receipt, including the original
alternate-symbol refusals. Reject duplicate JSON keys, nonfinite values, extra
fields, another provider/endpoint/query/as-of date, a wrong listed-right unit or
identity, changed preimages, duplicate/extra/path-escaping archive members and
unbounded expansion. A new generic frozen quote type derives exact decimal
strings only from the authenticated raw response, preserving its numeric
semantics without rounding. Existing preparation modules containing actual
price literals and both private payload files stay outside the public source
closure. The loader grants captured-market-input authority only. It does not
grant legal settlement, preopen quote availability or financial admission.

`p01_celg_input_transport.authenticate_capsule(descriptor, destination, key=...)`
is the outer-host interface. It uses the existing generic release getter
`alpaca_fit_stage.acquire` and `seal.decrypt`, requires a fresh disjoint
destination, verifies full length/SHA/GCM before reading the manifest, then checks
every manifest field and complete two-file inventory before decoding either
payload. Its durable private authentication receipt binds the descriptor,
ciphertext, manifest, both files and original crypto implementation. The unchanged
old two-asset `stage.py` request and both old extractors retain their schemas.

Mount that authenticated directory read-only as `/celg-input` and the public
descriptor read-only as `/celg-input-descriptor.json`.
`load_authenticated_input(root, descriptor)` rechecks the complete descriptor,
receipt, retained ciphertext/manifest and every plaintext preimage before
returning the immutable result. It performs no download and receives no key. The
result exposes `.quote.model_dump(mode='json')` and the compressed/raw/capture,
manifest, ciphertext and combined input identity hashes. Outer-host authenticated
admission and read-only confinement are prerequisites; a receipt alone is not
independent provider authentication.

Local preparation creates a new private CASE directory, seals the existing two
files once and independently authenticates that concrete ciphertext through the
same loader without network access. Preserve all newly produced qualification
files and the exact cipher for retries. Publish only the safe descriptor: unique
asset name/URL, hashes, sizes and provenance. No raw response, actual quote values,
capture JSON or key enters public Git or public artifacts.

Versioned encrypted INPUT release assets follow the existing input retention
mechanism. They have no seven-day expiry configured by this code. The separate
qualifier/financial OUTPUT artifacts retain the already approved seven-day
Actions setting. That setting does not expire the input release or protected
private archive. No new expiry/deletion policy is introduced.

Tests use fixed captured bytes and ephemeral random test keys, never a canonical
runtime. Cover the actual crypto framing/AAD/nonce, bad GCM, manifest/inventory
changes, wrong preimages/provider/as-of/unit and extra fields, plus a guard-removal
falsifier. The one real local preparation may recover the existing research key
only to seal/authenticate this capsule; it starts no provider request, container,
financial replay, upload or cleanup.

Use native extended Windows paths for every private capsule path, including the
long content-addressed filename. A failed local preparation remains intact. An
explicit existing-cipher recovery may copy its exact bytes into a fresh directory
and qualify them against the same expected manifest and source preimages. It
never reseals a retry, changes the nonce or deletes the failed preparation.
