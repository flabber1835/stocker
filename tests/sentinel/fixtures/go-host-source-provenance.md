# Historical GO host-overlay source

The two gzip files contain exact Git blobs exported from verified revision
`c0d4ed7b6888e63c9d49584c6fcf063c6950f8f9` of `flabber1835/stocker`.
They freeze the already applied four-argument host repair. Historical overlay
tests must not reconstruct old source from a current script that keeps changing.

| Fixture | Git path | Decompressed SHA256 |
| --- | --- | --- |
| `go-host-c0d4ed7b.py.gz` | `scripts/sentinel_go_validate.py` | `4d6bc501a035b450d6d3d1b750ab2785fc5a4ca8489acb150e11fab0efc4120b` |
| `go-entry-host-c0d4ed7b.py.gz` | `scripts/sentinel_go_validate_entry.py` | `f2ed521a8c97f5e0e3abb9a5163664fee151fd1da33203b8cc3bb547c1216e5c` |

Removing only the documented `SENTINEL_TEST_IMAGE_DIGEST` handoffs recovers the
independently pinned complete `dda0195c` predecessor modules:
`66cd2d8493e7e722bb5fad95003a3e969e9e56a7ed88b863d2b4bc07f60cca79` and
`f1155a3e73d2cd8abf15150f939f171c3cbbd6c382a27b950980cc7e50f57c8e`.
The original pins, loader allowlist, whole-module neighbor comparison and actual
child-identity refusal/falsifier tests are unchanged. Gzip uses a zero timestamp;
tests authenticate decompressed bytes. These are source fixtures, not financial
results or authorization to apply the historical overlay to a newer release.
