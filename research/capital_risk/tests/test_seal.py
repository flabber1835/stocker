import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("risk_seal", Path(__file__).parents[1] / "seal.py")
seal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seal)


class TransferGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".capital-risk-test-", dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.key = bytes(range(32))

    def asset(self, payload):
        path = self.root / "asset.enc"
        with path.open("wb") as output:
            writer = seal.EncryptWriter(output, self.key)
            writer.write(payload[:7]); writer.write(payload[7:]); writer.finish()
        return path

    def archive(self, extra=None, member_name="data/file", wrong_hash=False):
        payload = b"synthetic test data"
        manifest = dict(schema="research.capital-risk-inputs/1", members={member_name:dict(
            bytes=len(payload), sha256="0"*64 if wrong_hash else hashlib.sha256(payload).hexdigest())})
        raw = json.dumps(manifest).encode()
        path = self.root / "data.tar"
        with tarfile.open(path, "w") as tar:
            for name, value in [("manifest.json", raw), (member_name, payload)]:
                info=tarfile.TarInfo(name);info.size=len(value);tar.addfile(info,io.BytesIO(value))
            if extra is not None:
                tar.addfile(extra, io.BytesIO(b""))
        return path, hashlib.sha256(raw).hexdigest()

    def test_stream_roundtrip(self):
        value = b"synthetic" * 200000
        asset = self.asset(value)
        target = self.root / "plain"
        seal.decrypt(asset, target, self.key, seal.sha256_file(asset))
        self.assertEqual(target.read_bytes(), value)

    def test_tamper_wrong_key_and_truncation_never_publish_plaintext(self):
        asset=self.asset(b"synthetic confidential" * 100)
        original=asset.read_bytes()
        for value,key in [(original, b"x"*32), (original[:-1],self.key),
                          (original[:30]+bytes([original[30]^1])+original[31:],self.key)]:
            asset.write_bytes(value)
            target=self.root / "refused"
            with self.assertRaises(Exception):
                seal.decrypt(asset,target,key,seal.sha256_file(asset))
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name("refused.partial").exists())

    def test_manifest_inventory_roundtrip(self):
        path,digest=self.archive()
        seal.extract_verified(path,self.root/"out",digest)
        self.assertEqual((self.root/"out/data/file").read_bytes(),b"synthetic test data")

    def test_paths_links_duplicates_and_unlisted_members_refuse(self):
        for i,name in enumerate(["../escape", "/absolute", "a/../b", "a\\b", "C:/data"]):
            with self.subTest(name=name),self.assertRaises(ValueError):
                path,digest=self.archive(member_name=name)
                seal.extract_verified(path,self.root/f"out-{i}",digest)
        extras=[tarfile.TarInfo("unlisted"),tarfile.TarInfo("data/file")]
        link=tarfile.TarInfo("data/file");link.type=tarfile.SYMTYPE;link.linkname="../../escape"
        extras.append(link)
        for i,extra in enumerate(extras):
            with self.subTest(extra=i),self.assertRaises(ValueError):
                path,digest=self.archive(extra=extra)
                seal.extract_verified(path,self.root/f"extra-{i}",digest)

    def test_plaintext_hash_mismatch_refuses(self):
        path,digest=self.archive(wrong_hash=True)
        with self.assertRaisesRegex(ValueError,"REFUSED_MEMBER_HASH"):
            seal.extract_verified(path,self.root/"bad-hash",digest)


if __name__ == "__main__":
    unittest.main()
