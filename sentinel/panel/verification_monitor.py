"""Current dashboard consumes the independent verifier's durable receipts."""
from sentinel.panel import authority_reader as financial


def paper_unknown(include_paper, detail, retained=None, *, checking_until=None):
    rows, details, history, errors = financial._unknown(True, detail, retained,
                                                      checking_until=checking_until)
    return [row for row in rows if row.key == 'paper_reconciliation'], details, history, errors


class DurableProjection:
    """The production panel is only a consumer and cannot create proof workers."""

    def read(self, database_url, *, include_paper=True):
        from sentinel.panel import read_projection
        try:
            return read_projection.read(database_url, include_paper=include_paper)
        except Exception as exc:
            return financial._unknown(include_paper,
                'durable verification unavailable: '+type(exc).__name__)


monitor = DurableProjection()
