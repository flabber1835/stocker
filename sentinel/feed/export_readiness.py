"""One bounded export-status sweep; pending generation does not starve later files."""
from sentinel.feed import acquisition_work, progress, snapshot_export


def probe_all(requests):
    snapshots = []
    pending = None
    for table, params in requests:
        try:
            snapshots.append(snapshot_export.probe_snapshot(table, params=params))
        except snapshot_export.ExportPending as exc:
            pending = pending or exc
    if pending is not None:
        progress.emit("source_preflight", "working", reason="EXPORT_GENERATION_PENDING",
                      ready=len(snapshots), parts=len(requests),
                      retry_seconds=int(pending.delay),
                      remaining_seconds=int(acquisition_work.remaining() or 0))
        raise pending
    return snapshots
