"""PostgreSQL archive name classification shared with the Python 3.8 host."""
import re
import sys

_SEGMENT = re.compile(r"[0-9A-F]{24}\Z")
_BACKUP = re.compile(r"([0-9A-F]{24})\.([0-9A-F]{8})\.backup\Z")
_HISTORY = re.compile(r"([0-9A-F]{8})\.history\Z")


def archive_kind(name: str, segment_size: int) -> str:
    if segment_size <= 0 or 0x100000000 % segment_size:
        raise ValueError("unsupported WAL segment size")
    backup = _BACKUP.fullmatch(name)
    history = _HISTORY.fullmatch(name)
    if history is not None:
        timeline = int(history.group(1), 16)
    else:
        segment = backup.group(1) if backup is not None else name
        if _SEGMENT.fullmatch(segment) is None:
            raise ValueError("malformed WAL filename")
        timeline = int(segment[:8], 16)
        if int(segment[16:24], 16) >= 0x100000000 // segment_size:
            raise ValueError("WAL segment outside configured log geometry")
        if backup is not None and int(backup.group(2), 16) >= segment_size:
            raise ValueError("backup-history offset exceeds WAL segment size")
    if timeline == 0:
        raise ValueError("archive object has an invalid zero timeline")
    return "METADATA" if backup is not None or history is not None else "SEGMENT"


if __name__ == "__main__":
    try:
        print(archive_kind(sys.argv[1], int(sys.argv[2])))
    except (ValueError, IndexError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
