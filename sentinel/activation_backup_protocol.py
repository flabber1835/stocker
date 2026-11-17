"""Wire result for a busy backup proof before an activation mutation."""

import json

EXIT_BACKUP_PROOF_BUSY = 76
BACKUP_PROOF_BUSY_MARKER = "SENTINEL_ACTIVATION_BACKUP_PROOF_BUSY="
BACKUP_PROOF_BUSY_SCHEMA = "sentinel.activation-backup-proof-busy/1"


def backup_proof_busy_record(command: str) -> str:
    return BACKUP_PROOF_BUSY_MARKER + json.dumps(
        {"schema": BACKUP_PROOF_BUSY_SCHEMA, "command": command},
        sort_keys=True,
        separators=(",", ":"),
    )
