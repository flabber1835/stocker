"""Wire result for a native debit fee awaiting account cash posting."""

import json

EXIT_NATIVE_FEE_WAIT = 75
NATIVE_FEE_WAIT_MARKER = "SENTINEL_NATIVE_FEE_WAIT="
NATIVE_FEE_WAIT_SCHEMA = "sentinel.native-fee-posting-wait/1"


def native_fee_wait_record(decision_session: str) -> str:
    return NATIVE_FEE_WAIT_MARKER + json.dumps(
        {"schema": NATIVE_FEE_WAIT_SCHEMA, "decision_session": decision_session},
        sort_keys=True,
        separators=(",", ":"),
    )
