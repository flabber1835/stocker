from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping, Optional


def payload(completed, *, marker: str) -> Optional[Mapping[str, object]]:
    matches = []
    for line in (completed.stdout or "").splitlines():
        if not line.startswith(marker):
            continue
        try:
            value = json.loads(line[len(marker):])
        except ValueError:
            return None
        if not isinstance(value, dict):
            return None
        matches.append(value)
    return matches[0] if len(matches) == 1 else None


def safe_detail(value: object) -> Optional[str]:
    detail = str(value or "").strip()
    if not detail:
        return None
    lowered = detail.lower()
    prohibited = (
        "http://", "https://", "api_key", "api-key", "password", "authorization",
        "postgres://", "postgresql://", "apca-api-",
    )
    if any(item in lowered for item in prohibited) or re.search(r"[\r\n\x00]", detail):
        return None
    if len(detail) <= 500:
        return detail
    digest = hashlib.sha256(detail.encode("utf-8", errors="replace")).hexdigest()[:16]
    return detail[:445] + " ... [sha256:%s]" % digest
