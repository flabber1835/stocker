"""Minimum host interpreter exercises the same promotion policy and reader."""
from copy import deepcopy
import unittest

from scripts import sentinel_ci_promotion as policy
from scripts import sentinel_ci_certification_verify as verifier
from tools import sentinel_ci_promote as promote


class PromotionHostCompatibility(unittest.TestCase):
    def images(self):
        before = {"Id": "sha256:" + "1" * 64, "Architecture": "amd64", "Os": "linux",
                  "RootFS": {"Type": "layers", "Layers": ["sha256:" + "2" * 64]},
                  "Config": {"User": "10001", "Entrypoint": ["python"], "Env": [
                      "SENTINEL_IMAGE_SOURCE_REVISION=" + "a" * 40],
                      "Labels": {"org.opencontainers.image.revision": "a" * 40}}}
        after = deepcopy(before)
        after["Id"] = "sha256:" + "3" * 64
        after["Config"]["Labels"]["org.opencontainers.image.revision"] = "b" * 40
        after["Config"]["Env"] = ["SENTINEL_IMAGE_SOURCE_REVISION=" + "b" * 40]
        return before, after

    def test_metadata_only_is_accepted(self):
        policy.verify_images(*self.images(), "a" * 40, "b" * 40)

    def test_changed_layers_are_refused(self):
        before, after = self.images()
        after["RootFS"]["Layers"] = ["sha256:" + "4" * 64]
        with self.assertRaises(policy.PromotionRefused):
            policy.verify_images(before, after, "a" * 40, "b" * 40)

    def test_changed_execution_user_is_refused(self):
        before, after = self.images()
        after["Config"]["User"] = "root"
        with self.assertRaises(policy.PromotionRefused):
            policy.verify_images(before, after, "a" * 40, "b" * 40)

    def test_workflow_identity_does_not_coerce(self):
        for value in (True, "1", 1.5, 0, -1):
            with self.subTest(value=value), self.assertRaises(policy.PromotionRefused):
                policy.positive(value)

    def test_new_schema_reuses_strict_host_json_reader(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'null', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(verifier.CertificationVerificationRefused):
                promote._json_bytes(raw, "REFUSED", "promotion")


if __name__ == "__main__":
    unittest.main()
