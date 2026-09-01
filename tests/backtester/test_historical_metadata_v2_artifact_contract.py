import tempfile
import unittest
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base


class HistoricalMetadataV2ArtifactContractTests(unittest.TestCase):
    def test_http_cache_is_excluded_from_portable_checksum_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "retained.json").write_text("{}\n", encoding="utf-8")
            cache = root / "discovery" / ".http-cache"
            cache.mkdir(parents=True)
            (cache / "response").write_bytes(b"ephemeral")

            base.write_checksums(root, exclude={".http-cache"})
            manifest = (root / "SHA256SUMS.txt").read_text(encoding="utf-8")
            self.assertIn("retained.json", manifest)
            self.assertNotIn(".http-cache", manifest)

            (cache / "response").unlink()
            cache.rmdir()
            cache.parent.rmdir()
            self.assertEqual(base.verify_checksums(root)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
