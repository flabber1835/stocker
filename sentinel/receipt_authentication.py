"""The shared receipt HMAC primitive, without feed or numerical dependencies."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Mapping

KEY_ENV = 'SENTINEL_PUBLICATION_RECEIPT_KEY'


class ReceiptKeyUnavailable(ValueError):
    pass


def sign(payload: Mapping[str, object]) -> str:
    secret = os.environ.get(KEY_ENV, '').strip().encode('utf-8')
    if len(secret) < 32:
        raise ReceiptKeyUnavailable(f'{KEY_ENV} must contain at least 32 bytes')
    encoded = json.dumps(dict(payload), sort_keys=True,
                         separators=(',', ':'), default=str).encode('utf-8')
    return hmac.new(secret, encoded, hashlib.sha256).hexdigest()
