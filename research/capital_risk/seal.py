"""Authenticated streaming transfer; no trading and no credential discovery."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"CRSEAL01"
BLOCK = 1024 * 1024
MAX_ASSET = 2 * 1024**3 - 1
MAX_EXPANDED = 4 * 1024**3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while part := stream.read(BLOCK):
            digest.update(part)
    return digest.hexdigest()


class EncryptWriter:
    def __init__(self, destination: BinaryIO, key: bytes):
        if len(key) != 32:
            raise ValueError("REFUSED_KEY_LENGTH")
        self.destination = destination
        header = MAGIC + os.urandom(12)
        self.cipher = Cipher(algorithms.AES256(key), modes.GCM(header[-12:])).encryptor()
        self.cipher.authenticate_additional_data(header)
        self.destination.write(header)
        self.size = len(header)
        self.finished = False

    def write(self, value: bytes) -> int:
        if self.finished or self.size + len(value) + 16 > MAX_ASSET:
            raise ValueError("REFUSED_ASSET_SIZE_OR_CLOSED")
        self.destination.write(self.cipher.update(value))
        self.size += len(value)
        return len(value)

    def finish(self) -> None:
        if self.finished:
            raise ValueError("REFUSED_DOUBLE_FINALIZE")
        self.destination.write(self.cipher.finalize())
        self.destination.write(self.cipher.tag)
        self.finished = True


def decrypt(asset: Path, destination: Path, key: bytes, expected_sha256: str) -> None:
    """Publish plaintext only after its complete authentication succeeds."""
    if len(key) != 32 or asset.stat().st_size > MAX_ASSET:
        raise ValueError("REFUSED_KEY_OR_ASSET_SIZE")
    if sha256_file(asset) != expected_sha256:
        raise ValueError("REFUSED_CIPHERTEXT_HASH")
    if destination.exists():
        raise ValueError("REFUSED_OVERWRITE")
    partial = destination.with_name(destination.name + ".partial")
    if partial.exists():
        raise ValueError("REFUSED_EXISTING_PARTIAL")
    try:
        with asset.open("rb") as source, partial.open("xb") as output:
            os.chmod(partial, 0o600)
            header = source.read(len(MAGIC) + 12)
            if len(header) != 20 or not header.startswith(MAGIC):
                raise ValueError("REFUSED_ENCRYPTION_HEADER")
            remaining = asset.stat().st_size - len(header) - 16
            if remaining < 0:
                raise ValueError("REFUSED_TRUNCATED_ASSET")
            source.seek(-16, io.SEEK_END)
            tag = source.read(16)
            source.seek(len(header))
            cipher = Cipher(algorithms.AES256(key), modes.GCM(header[-12:], tag)).decryptor()
            cipher.authenticate_additional_data(header)
            while remaining:
                part = source.read(min(BLOCK, remaining))
                if not part:
                    raise ValueError("REFUSED_TRUNCATED_ASSET")
                output.write(cipher.update(part))
                remaining -= len(part)
            output.write(cipher.finalize())
        partial.rename(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(p in {"", ".", ".."} for p in name.split("/"))
            or path.as_posix() != name):
        raise ValueError("REFUSED_MEMBER_PATH")
    return name


def extract_verified(archive: Path, root: Path, expected_manifest_sha256: str) -> dict:
    """Extract a manifest-bounded inventory, never tarfile.extract/all."""
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    with tarfile.open(archive, "r|") as tar:
        first = tar.next()
        if (first is None or first.name != "manifest.json" or not first.isfile()
                or first.size > 2 * BLOCK):
            raise ValueError("REFUSED_FIRST_MANIFEST")
        payload = tar.extractfile(first).read()
        if hashlib.sha256(payload).hexdigest() != expected_manifest_sha256:
            raise ValueError("REFUSED_MANIFEST_HASH")
        manifest = json.loads(payload)
        if manifest["schema"] != "research.capital-risk-inputs/1":
            raise ValueError("REFUSED_MANIFEST_SCHEMA")
        members = manifest["members"]
        if not members or len(members) > 5000:
            raise ValueError("REFUSED_MEMBER_COUNT")
        if sum(v["bytes"] for v in members.values()) > MAX_EXPANDED:
            raise ValueError("REFUSED_EXPANDED_SIZE")
        for name, spec in members.items():
            safe_name(name)
            if name == "manifest.json" or not isinstance(spec["bytes"], int) or spec["bytes"] < 0:
                raise ValueError("REFUSED_MANIFEST_MEMBER")
        seen = set()
        # tar iteration includes its cached first member: consume the remainder explicitly.
        while member := tar.next():
            name = safe_name(member.name)
            if name in seen or name not in members or not member.isfile():
                raise ValueError("REFUSED_MEMBER_TYPE_OR_INVENTORY")
            spec = members[name]
            if member.size != spec["bytes"]:
                raise ValueError("REFUSED_MEMBER_SIZE")
            destination = root / name
            if not destination.resolve().is_relative_to(root.resolve()):
                raise ValueError("REFUSED_EXTRACTION_ESCAPE")
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with tar.extractfile(member) as source, destination.open("xb") as output:
                os.chmod(destination, 0o600)
                while part := source.read(BLOCK):
                    digest.update(part)
                    output.write(part)
            if digest.hexdigest() != spec["sha256"]:
                raise ValueError("REFUSED_MEMBER_HASH")
            seen.add(name)
        if seen != set(members):
            raise ValueError("REFUSED_MISSING_MEMBER")
    return manifest
