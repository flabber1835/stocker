"""Build bounded CSV archives for offline input tests."""
import io
import zipfile


def _zip_csv(name: str, header: str, rows: list[list[str]]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        body = header + "\n" + "\n".join(",".join(row) for row in rows) + "\n"
        archive.writestr(name, body)
    return out.getvalue()


def _zip_tickers(rows: list[list[str]]) -> bytes:
    return _zip_csv("TICKERS.csv", "table,permaticker,ticker", rows)
