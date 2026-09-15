"""Append-only retained payloads, causal event receipts and failure diagnostics."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import traceback


def plain(value):
    if callable(getattr(value,"to_dict",None)):
        return plain(value.to_dict())
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, Enum):
        return plain(value.value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (date, Decimal, Path)):
        return str(value)
    return value


def encode(value):
    return json.dumps(plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


class Divergence(AssertionError):
    def __init__(self, gate, expected, actual):
        self.gate, self.expected, self.actual = gate, plain(expected), plain(actual)
        super().__init__(f"{gate}: expected={str(self.expected)[:300]} actual={str(self.actual)[:300]}")


def require(gate, expected, actual):
    if expected != actual:
        raise Divergence(gate, expected, actual)


class Evidence:
    def __init__(self, root: Path, identity: dict):
        self.root = root
        root.mkdir(parents=True, exist_ok=False)
        (root / "objects").mkdir()
        self.stream = (root / "events.jsonl").open("xb", buffering=0)
        self.previous = "0" * 64
        self.sequence = 0
        self.last_at = None
        self.phases = {}
        self.identity = identity
        self.write("IDENTITY.json", identity)

    def file(self, source):
        with Path(source).open("rb") as stream:
            key = hashlib.file_digest(stream, "sha256").hexdigest()
        path = self.root / "objects" / (key + ".blob")
        if not path.exists():
            with path.open("xb") as target, Path(source).open("rb") as stream:
                shutil.copyfileobj(stream, target)
                target.flush()
                os.fsync(target.fileno())
        return dict(blob_sha256=key, bytes=path.stat().st_size)

    def write(self, name, value):
        with (self.root / name).open("xb") as output:
            output.write(encode(value) + b"\n")
            output.flush()
            os.fsync(output.fileno())

    def object(self, value):
        body = encode(value)
        key = hashlib.sha256(body).hexdigest()
        path = self.root / "objects" / (key + ".json.gz")
        if path.exists():
            if gzip.decompress(path.read_bytes()) != body:
                raise ValueError("content-addressed evidence was modified")
        else:
            with path.open("xb") as output:
                output.write(gzip.compress(body, mtime=0))
                output.flush()
                os.fsync(output.fileno())
        return key

    def event(self, *, at: datetime, session: str, phase: str, payload):
        if at.tzinfo is None or at.utcoffset() != timezone.utc.utcoffset(at):
            raise ValueError("event clock must be explicit UTC")
        if self.last_at is not None and at < self.last_at:
            raise ValueError("event clock moved backwards")
        if str(at.date()) < session:
            raise ValueError("event refers to a future market session")
        key = self.object(dict(run_identity=self.identity,payload=payload) if self.sequence==0 else payload)
        event = dict(schema="full-system-event/1", sequence=self.sequence,
            at=at.isoformat(), session=session, phase=phase, payload_sha256=key,
            previous_sha256=self.previous)
        event["sha256"] = digest(event)
        self.stream.write(encode(event) + b"\n")
        os.fsync(self.stream.fileno())
        self.sequence += 1
        self.previous, self.last_at = event["sha256"], at
        self.phases.setdefault(session, []).append(phase)
        return event

    @contextmanager
    def boundary(self, phase, *, at, session, before=None, inputs=None):
        result = {}
        start = time.monotonic()
        self.event(at=at, session=session, phase=phase + ":start",
                   payload=dict(before=before, inputs=inputs))
        try:
            yield result
        except BaseException as exc:
            failure = dict(error_type=type(exc).__name__, error=str(exc),
                traceback=traceback.format_exc(), seconds=time.monotonic()-start)
            if isinstance(exc, Divergence):
                failure.update(gate=exc.gate, expected=exc.expected, actual=exc.actual)
            self.event(at=at, session=session, phase=phase + ":failure", payload=failure)
            if not (self.root / "FIRST_FAILURE.json").exists():
                self.write("FIRST_FAILURE.json", dict(session=session, phase=phase, **failure))
            raise
        else:
            self.event(at=at, session=session, phase=phase + ":complete",
                       payload=dict(result=result, seconds=time.monotonic()-start))

    def close(self):
        self.stream.close()


def verify(root: Path):
    previous = "0" * 64
    at = None
    count = 0
    checked_blobs = set()
    def blobs(value):
        if isinstance(value,dict):
            if set(value)=={"blob_sha256","bytes"}:
                key=value["blob_sha256"]
                if key not in checked_blobs:
                    path=root/"objects"/(key+".blob")
                    require("retained_blob_size",value["bytes"],path.stat().st_size)
                    with path.open("rb") as source:
                        require("retained_blob_digest",key,hashlib.file_digest(source,"sha256").hexdigest())
                    checked_blobs.add(key)
            for child in value.values():
                blobs(child)
        elif isinstance(value,list):
            for child in value:
                blobs(child)
    for count, line in enumerate((root / "events.jsonl").open("rb"), 1):
        event = json.loads(line)
        stored = event.pop("sha256")
        require("event_sequence", count-1, event["sequence"])
        require("event_previous", previous, event["previous_sha256"])
        require("event_digest", stored, digest(event))
        moment = datetime.fromisoformat(event["at"])
        if (moment.tzinfo is None or moment.utcoffset() != timezone.utc.utcoffset(moment)
                or (at is not None and moment < at) or str(moment.date()) < event["session"]):
            raise ValueError("invalid retained event clock")
        body = gzip.decompress((root / "objects" / (event["payload_sha256"] + ".json.gz")).read_bytes())
        require("retained_payload", event["payload_sha256"], hashlib.sha256(body).hexdigest())
        payload=json.loads(body)
        if count==1:
            require("run_identity_commitment",json.loads((root/"IDENTITY.json").read_text()),payload["run_identity"])
        blobs(payload)
        previous, at = stored, moment
    return dict(events=count, final_sha256=previous, verified_blobs=len(checked_blobs))
