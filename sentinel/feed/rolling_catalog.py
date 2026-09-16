"""Reviewed catalog witnesses for the additive rolling-snapshot relations."""

COLUMNS = {
    "sentinel_snapshot_evidence": {
        "evidence_sha256": ("text", True), "payload": ("jsonb", True),
    },
    "sentinel_price_candidates": {
        "candidate_id": ("uuid", True), "window_start": ("date", True),
        "window_end": ("date", True), "session_axis": ("jsonb", True),
        "reference_sha256": ("text", True), "source_evidence_sha256": ("text", True),
        "expected_publication_version": ("bigint", False),
        "dependencies_sha256": ("text", True), "snapshot_id": ("text", False),
        "manifest": ("jsonb", False),
    },
    "sentinel_snapshot_bars": {
        "candidate_id": ("uuid", True), "security_id": ("text", True),
        "session": ("date", True), "ticker": ("text", True),
        "close_signal": ("double precision", False),
        "close_unadjusted": ("double precision", True),
        "open_unadjusted": ("double precision", False),
        "volume": ("double precision", False),
        "split_ratio": ("double precision", True),
        "dividend_per_share": ("double precision", True),
    },
    "sentinel_snapshot_benchmarks": {
        "candidate_id": ("uuid", True), "session": ("date", True),
        "spy_total_return": ("double precision", True),
        "bil_open_signal": ("double precision", False),
        "bil_close_signal": ("double precision", True),
        "bil_close_adjusted": ("double precision", False),
        "bil_close_unadjusted": ("double precision", True),
    },
}
PRIMARY_KEYS = {
    "sentinel_snapshot_evidence": "primary key (evidence_sha256)",
    "sentinel_price_candidates": "primary key (candidate_id)",
    "sentinel_snapshot_bars": "primary key (candidate_id, session, security_id)",
    "sentinel_snapshot_benchmarks": "primary key (candidate_id, session)",
}
TRIGGERS = {
    table: {
        "snapshot_immutable": (
            "before delete or update", "for each row",
            "execute function sentinel_snapshot_immutable()"),
    }
    for table in COLUMNS if table != "sentinel_price_candidates"
}
for _table in ("sentinel_snapshot_bars", "sentinel_snapshot_benchmarks"):
    TRIGGERS[_table]["snapshot_insert"] = (
        "before insert", "for each row", "execute function sentinel_snapshot_insert()")
TRIGGERS["sentinel_price_candidates"] = {
    "snapshot_immutable": (
        "before delete", "for each row", "execute function sentinel_snapshot_immutable()"),
    "snapshot_seal": (
        "before update", "for each row", "execute function sentinel_snapshot_seal()"),
}
CONSTRAINTS = {
    "sentinel_snapshot_evidence": (
        ("c", ("evidence_sha256", "[0-9a-f]{64}")),
        ("c", ("jsonb_typeof(payload)", "object")),
    ),
    "sentinel_price_candidates": (
        ("f", ("foreign key (reference_sha256)", "sentinel_snapshot_evidence")),
        ("f", ("foreign key (source_evidence_sha256)", "sentinel_snapshot_evidence")),
        ("c", ("window_end > window_start",)),
        ("c", ("jsonb_array_length(session_axis)", "300")),
        ("c", ("snapshot_id is null", "manifest is null", "object")),
    ),
}
for _table in ("sentinel_snapshot_bars", "sentinel_snapshot_benchmarks"):
    CONSTRAINTS[_table] = (
        ("f", ("foreign key (candidate_id)", "sentinel_price_candidates")),
        *[("c", (name, ">= 0" if name in ("volume", "dividend_per_share") else "> 0",
                  "infinity"))
          for name, (kind, _) in COLUMNS[_table].items() if kind == "double precision"],
    )
