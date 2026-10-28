"""Dated operating-issuer evidence; no provider access on the resolution path.

SEC CIK associations are scoped evidence, not universal economic-parent IDs.
See docs/paper-issuer-admission.md. Display names never establish identity.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import cached_property
import hashlib
import json
from pathlib import Path
import re
from typing import Annotated, Literal
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SEC_ENDPOINT = "https://www.sec.gov/files/company_tickers_exchange.json"
POLICY = "SEC_CIK_LISTED_OPERATING_ISSUER_PAPER_V1"
DEFAULT_USER_AGENT = (
    "Sentinel-issuer-reference/1.0 (+https://github.com/flabber1835/stocker)"
)
MAX_AGE = timedelta(days=30)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
BUNDLED_PATH = Path(__file__).resolve().parents[1] / "issuer-reference-sec-20261027.json"
# Independent source-file trust is also bound by the reviewed runtime source seal.
BUNDLED_SNAPSHOT_SHA256 = "d466ae28d724ca3516f87c8e50bc924599ced2665a137d5bb56e386079db2d69"
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CIK = Annotated[str, Field(pattern=r"^[0-9]{10}$")]
Symbol = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9.-]{0,31}$")]
SourceMethod = Literal["WEB_EXTRACTED_REPRESENTATION", "DIRECT_HTTP_BODY"]
Coverage = Literal["PARTIAL", "COMPLETE_SOURCE"]
ObservationTimeBasis = Literal["RECORDED_REQUEST_START", "CONSERVATIVE_PRIOR_UTC_BOUND"]
_SUPPORTED_TYPES = {
    "Common Stock": "Common Stock", "REIT": "REIT",
    "MLP": "Partnership Shares", "Ltd Part": "Partnership Shares",
}
_ADR_TYPES = {"ADR", "GDR", "NY Reg Shrs"}
_EXCHANGES = {"NYSE": "NYSE", "NASDAQ": "Nasdaq", "Nasdaq": "Nasdaq",
              "CBOE": "CBOE", "BATS": "CBOE", "TXSE": "TXSE"}


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("issuer reference timestamps must be UTC-aware")
    return value.astimezone(timezone.utc)


def _now(value: datetime | None) -> datetime:
    return _utc(value or datetime.now(timezone.utc))


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IssuerAssociation(Contract):
    cik: CIK
    ticker: Symbol
    exchange: str | None

    @field_validator("cik")
    @classmethod
    def positive_cik(cls, value):
        if int(value) == 0:
            raise ValueError("CIK zero is not issuer evidence")
        return value


class SourceProvenance(Contract):
    source_url: Literal["https://www.sec.gov/files/company_tickers_exchange.json"] = SEC_ENDPOINT
    source_method: SourceMethod
    coverage: Coverage
    observed_at_utc: datetime
    expires_at_utc: datetime
    observation_time_basis: ObservationTimeBasis = "RECORDED_REQUEST_START"
    content_sha256: Digest
    content_digest_scope: Literal["NORMALIZED_ASSOCIATIONS_V1"] = "NORMALIZED_ASSOCIATIONS_V1"
    capture_sha256: Digest | None = None
    raw_http_sha256: Digest | None = None

    _timestamps = field_validator("observed_at_utc", "expires_at_utc")(_utc)

    @model_validator(mode="after")
    def bounded_provenance(self):
        if not timedelta(0) < self.expires_at_utc - self.observed_at_utc <= MAX_AGE:
            raise ValueError("issuer evidence expiry must be within 30 days")
        if self.source_method == "WEB_EXTRACTED_REPRESENTATION":
            if self.raw_http_sha256 is not None:
                raise ValueError("web-extracted evidence has no original HTTP body hash")
        elif self.raw_http_sha256 is None:
            raise ValueError("direct HTTP evidence requires its original body hash")
        return self


class UnderlyingIssuerCorroboration(Contract):
    """Explicit ADR-to-operating-issuer relationship from an issuer disclosure."""

    cik: CIK
    symbols: tuple[Symbol, ...]
    exchange: Literal["NYSE", "Nasdaq", "CBOE", "TXSE"]
    source_url: str
    source_method: Literal["WEB_EXTRACTED_REPRESENTATION"] = "WEB_EXTRACTED_REPRESENTATION"
    observed_at_utc: datetime
    expires_at_utc: datetime
    observation_time_basis: ObservationTimeBasis = "RECORDED_REQUEST_START"
    statement: str = Field(min_length=20, max_length=2000)
    content_sha256: Digest

    _timestamps = field_validator("observed_at_utc", "expires_at_utc")(_utc)

    @model_validator(mode="after")
    def honest_disclosure(self):
        if (not self.symbols or len(self.symbols) != len(set(self.symbols))
                or not self.source_url.startswith((
                    "https://www.sec.gov/Archives/edgar/",
                    "https://www.investidorpetrobras.com.br/"))
                or not timedelta(0) < self.expires_at_utc - self.observed_at_utc <= MAX_AGE):
            raise ValueError("invalid underlying-issuer corroboration")
        body = self.model_dump(mode="json", exclude={"content_sha256"})
        if _digest(body) != self.content_sha256:
            raise ValueError("underlying-issuer corroboration digest mismatch")
        return self

    @classmethod
    def create(cls, **values):
        body = dict(values)
        body.setdefault("source_method", "WEB_EXTRACTED_REPRESENTATION")
        body.setdefault("observation_time_basis", "RECORDED_REQUEST_START")
        body["observed_at_utc"] = _timestamp(body["observed_at_utc"])
        body.setdefault("expires_at_utc", _utc(values["observed_at_utc"]) + MAX_AGE)
        body["expires_at_utc"] = _timestamp(body["expires_at_utc"])
        return cls.model_validate({**body, "content_sha256": _digest(body)})


class IssuerIdentity(Contract):
    status: Literal["VERIFIED", "UNRESOLVED"]
    issuer_id: str | None
    reason: str
    original_symbol: str
    reference_symbol: str | None
    cik: CIK | None
    snapshot_digest: Digest
    evidence_digest: Digest
    source_urls: tuple[str, ...]
    observed_at_utc: datetime
    expires_at_utc: datetime

    @model_validator(mode="after")
    def consistent_identity(self):
        verified = self.status == "VERIFIED"
        if (verified != (self.cik is not None)
                or self.issuer_id != (f"SEC_CIK:{self.cik}" if verified else None)
                or verified != (self.reference_symbol is not None)):
            raise ValueError("inconsistent issuer identity")
        if _digest(self.model_dump(mode="json", exclude={"evidence_digest"})) != self.evidence_digest:
            raise ValueError("issuer identity evidence digest mismatch")
        return self


class IssuerReferenceSnapshot(Contract):
    policy: Literal["SEC_CIK_LISTED_OPERATING_ISSUER_PAPER_V1"] = POLICY
    provenance: SourceProvenance
    associations: tuple[IssuerAssociation, ...]
    corroborations: tuple[UnderlyingIssuerCorroboration, ...] = ()
    snapshot_digest: Digest

    @model_validator(mode="after")
    def authenticated_representation(self):
        rows = [row.model_dump(mode="json") for row in self.associations]
        if not rows or _digest(rows) != self.provenance.content_sha256:
            raise ValueError("issuer association content digest mismatch")
        if len(rows) != len({_digest(row) for row in rows}):
            raise ValueError("duplicate issuer association row")
        body = self.model_dump(mode="json", exclude={"snapshot_digest"})
        if _digest(body) != self.snapshot_digest:
            raise ValueError("issuer snapshot digest mismatch")
        return self

    @classmethod
    def create(cls, *, observed_at_utc: datetime, associations,
               source_url: str = SEC_ENDPOINT,
               source_method: SourceMethod = "WEB_EXTRACTED_REPRESENTATION",
               coverage: Coverage = "PARTIAL", corroborations=(),
               capture_sha256: str | None = None,
               raw_http_sha256: str | None = None,
               observation_time_basis: ObservationTimeBasis = "RECORDED_REQUEST_START",
               expires_at_utc: datetime | None = None):
        observed = _utc(observed_at_utc)
        rows = tuple(IssuerAssociation.model_validate(row) for row in associations)
        proof = SourceProvenance(
            source_url=source_url, source_method=source_method, coverage=coverage,
            observed_at_utc=observed, expires_at_utc=expires_at_utc or observed + MAX_AGE,
            observation_time_basis=observation_time_basis,
            content_sha256=_digest([row.model_dump(mode="json") for row in rows]),
            capture_sha256=capture_sha256, raw_http_sha256=raw_http_sha256)
        underlying = tuple(UnderlyingIssuerCorroboration.model_validate(row)
                           for row in corroborations)
        body = {"policy": POLICY, "provenance": proof.model_dump(mode="json"),
                "associations": [row.model_dump(mode="json") for row in rows],
                "corroborations": [row.model_dump(mode="json") for row in underlying]}
        return cls.model_validate({**body, "snapshot_digest": _digest(body)})

    @property
    def sha256(self) -> str:
        return self.snapshot_digest

    @cached_property
    def _by_symbol(self):
        index: dict[str, list[IssuerAssociation]] = {}
        for row in self.associations:
            index.setdefault(row.ticker, []).append(row)
        return index

    def valid_at(self, now: datetime | None = None) -> bool:
        current = _now(now)
        return self.provenance.observed_at_utc <= current < self.provenance.expires_at_utc

    def _identity(self, symbol, reason, row=None, corroboration=None):
        verified = row is not None
        symbol = symbol if isinstance(symbol, str) else str(symbol)
        urls = (self.provenance.source_url,)
        expires = self.provenance.expires_at_utc
        observed = self.provenance.observed_at_utc
        if corroboration is not None:
            urls += (corroboration.source_url,)
            expires = min(expires, corroboration.expires_at_utc)
            observed = max(observed, corroboration.observed_at_utc)
        body = {"status": "VERIFIED" if verified else "UNRESOLVED",
                "issuer_id": f"SEC_CIK:{row.cik}" if verified else None,
                "reason": reason, "original_symbol": symbol,
                "reference_symbol": row.ticker if verified else None,
                "cik": row.cik if verified else None,
                "snapshot_digest": self.snapshot_digest, "source_urls": urls,
                "observed_at_utc": _timestamp(observed),
                "expires_at_utc": _timestamp(expires)}
        return IssuerIdentity.model_validate({**body, "evidence_digest": _digest(body)})

    def resolve(self, symbol: str, exchange: str | None, security_type: str | None,
                security_type2: str | None = None, *, now: datetime | None = None
                ) -> IssuerIdentity:
        """Resolve a retained, independently typed listing; never fetch or infer names."""
        current = _now(now)
        if not self.valid_at(current):
            return self._identity(symbol, "reference_expired_or_not_yet_observed")
        if not isinstance(symbol, str) or re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,31}", symbol) is None:
            return self._identity(str(symbol), "invalid_symbol")
        expected_exchange = _EXCHANGES.get(exchange or "")
        if expected_exchange is None:
            return self._identity(symbol, "unsupported_or_missing_exchange")
        # Only the documented final share-class separator can translate.
        candidates = {symbol}
        if re.fullmatch(r"[A-Z0-9]+[.-][A-Z]", symbol):
            candidates.add(symbol[:-2] + ("-" if symbol[-2] == "." else ".") + symbol[-1])
        all_rows = [row for candidate in candidates
                    for row in self._by_symbol.get(candidate, ())]
        if len({row.cik for row in all_rows}) > 1:
            return self._identity(symbol, "conflicting_cik_associations")
        matches = [row for row in all_rows if row.exchange == expected_exchange]
        if not matches:
            return self._identity(symbol, "missing_ticker_exchange_association")
        if len(matches) != 1:
            return self._identity(symbol, "ambiguous_class_separator_association")
        row = matches[0]
        if security_type in _ADR_TYPES:
            if security_type2 != "Depositary Receipt":
                return self._identity(symbol, "unsupported_security_type")
            proofs = [proof for proof in self.corroborations
                      if row.cik == proof.cik and row.ticker in proof.symbols
                      and proof.exchange == expected_exchange
                      and proof.observed_at_utc <= current < proof.expires_at_utc]
            if len(proofs) != 1:
                return self._identity(symbol, "underlying_issuer_not_corroborated")
            return self._identity(symbol, "verified_underlying_issuer", row, proofs[0])
        if (security_type not in _SUPPORTED_TYPES
                or _SUPPORTED_TYPES[security_type] != security_type2):
            return self._identity(symbol, "unsupported_security_type")
        return self._identity(symbol, "verified_sec_ticker_exchange_cik", row)

    def resolve_symbol(self, symbol: str, exchange: str | None = None, *,
                       security_type: str | None = None, security_type2: str | None = None,
                       now: datetime | None = None) -> IssuerIdentity:
        """Incumbent lookup; missing instrument classification remains unresolved."""
        if security_type is None:
            return self._identity(symbol, "incumbent_security_type_unavailable")
        return self.resolve(symbol, exchange, security_type, security_type2, now=now)


def load_snapshot(path: str | Path | None = None, *, expected_digest: str | None = None
                  ) -> IssuerReferenceSnapshot:
    """Load local evidence; a custom cache needs its independently retained digest."""
    selected = Path(path) if path is not None else BUNDLED_PATH
    raw = selected.read_bytes()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("issuer reference snapshot exceeds size bound")
    snapshot = IssuerReferenceSnapshot.model_validate_json(raw)
    trusted = expected_digest or (BUNDLED_SNAPSHOT_SHA256 if path is None else None)
    if trusted is None or snapshot.snapshot_digest != trusted:
        raise ValueError("issuer reference snapshot lacks the expected trusted digest")
    return snapshot


def evidence(snapshot: IssuerReferenceSnapshot, descriptors, *, now: datetime | None = None
             ) -> dict[str, IssuerIdentity]:
    result = {}
    for descriptor in descriptors:
        sid = descriptor.get("security_id")
        if not isinstance(sid, str) or not sid or sid in result:
            raise ValueError("issuer descriptor security identity is missing or duplicate")
        result[sid] = snapshot.resolve(
            descriptor.get("symbol", descriptor.get("ticker")), descriptor.get("exchange"),
            descriptor.get("security_type"), descriptor.get("security_type2"), now=now)
    return result


class RefreshResult(Contract):
    status: Literal["REFRESHED", "CACHED_VALID", "UNAVAILABLE"]
    snapshot: IssuerReferenceSnapshot | None
    reason: str
    retry_after_seconds: int = Field(default=3600, ge=60)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def refresh_snapshot(snapshot: IssuerReferenceSnapshot, *, now: datetime | None = None,
                     opener=None, timeout: float = 15,
                     user_agent: str = DEFAULT_USER_AGENT) -> RefreshResult:
    """One bounded offline-refresh request; failure never renews cached evidence.

    The caller schedules this outside execution, persists successful evidence,
    and respects retry_after_seconds. No retry, redirect, cache write or sleep.
    """
    current = _now(now)
    if not 0 < timeout <= 30 or not user_agent.strip():
        raise ValueError("issuer refresh timeout/identity is invalid")
    def unavailable(reason):
        valid = snapshot.valid_at(current)
        return RefreshResult(status="CACHED_VALID" if valid else "UNAVAILABLE",
                             snapshot=snapshot if valid else None, reason=reason)
    try:
        client = opener or build_opener(_NoRedirect())
        request = Request(SEC_ENDPOINT, headers={"User-Agent": user_agent,
                                                "Accept": "application/json"})
        with client.open(request, timeout=timeout) as response:
            if response.status != 200:
                return unavailable("sec_http_" + str(response.status))
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return unavailable("sec_response_exceeds_size_bound")
        payload = json.loads(raw)
        if (not isinstance(payload, dict)
                or payload.get("fields") != ["cik", "name", "ticker", "exchange"]
                or not isinstance(payload.get("data"), list) or not payload["data"]):
            return unavailable("sec_response_schema_invalid")
        rows = []
        for row in payload["data"]:
            if (not isinstance(row, list) or len(row) != 4
                    or type(row[0]) is not int or not 0 < row[0] < 10**10):
                return unavailable("sec_response_row_invalid")
            rows.append(IssuerAssociation(cik=f"{row[0]:010d}", ticker=row[2], exchange=row[3]))
        prior = {(row.ticker, row.exchange): row.cik for row in snapshot.associations}
        if any(prior.get((row.ticker, row.exchange), row.cik) != row.cik for row in rows):
            return unavailable("changed_cik_requires_identity_review")
        refreshed = IssuerReferenceSnapshot.create(
            observed_at_utc=current, associations=rows, source_method="DIRECT_HTTP_BODY",
            coverage="COMPLETE_SOURCE", corroborations=snapshot.corroborations,
            raw_http_sha256=hashlib.sha256(raw).hexdigest())
        return RefreshResult(status="REFRESHED", snapshot=refreshed, reason="sec_source_observed")
    except HTTPError as error:
        return unavailable("sec_http_" + str(error.code))
    except (URLError, TimeoutError, OSError):
        return unavailable("sec_transport_unavailable")
    except (ValueError, TypeError, UnicodeError):
        return unavailable("sec_response_invalid")
