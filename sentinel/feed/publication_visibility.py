"""Publication visibility policy for append-only SEP retirement generations."""
from __future__ import annotations


def visible_predicate(alias: str = "b") -> str:
    """Return the canonical SQL predicate for a publication-visible bar row.

    Physical presence is insufficient: a bar must belong to a published ingest
    generation (or predate run provenance), and no later published SEP retirement
    generation may tombstone its exact ``security_id/session/ticker`` key.

    Retirement keys are append-only evidence in
    ``sentinel_corpus_publications.evidence.source_retirement.keys``. A later bar
    generation naturally supersedes an older tombstone because the comparison is
    against the bar generation's publication version.
    """
    published = (
        f"({alias}.last_written_run_id IS NULL"
        f" OR EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
        f"            WHERE p.run_id = {alias}.last_written_run_id))"
    )
    return (
        f"({published} AND NOT EXISTS ("
        " SELECT 1 FROM sentinel_corpus_publications retirement"
        " CROSS JOIN LATERAL jsonb_array_elements("
        "   CASE WHEN jsonb_typeof("
        "       retirement.evidence #> '{source_retirement,keys}') = 'array'"
        "     THEN retirement.evidence #> '{source_retirement,keys}'"
        "     ELSE '[]'::jsonb END) retired_key"
        " WHERE retirement.evidence->>'kind'='sep_source_retirement'"
        f"   AND retirement.version > COALESCE((SELECT MAX(base.version)"
        "       FROM sentinel_corpus_publications base"
        f"       WHERE base.run_id={alias}.last_written_run_id), 0)"
        f"   AND retired_key->>'security_id'={alias}.security_id"
        f"   AND retired_key->>'session'={alias}.session::text"
        f"   AND retired_key->>'ticker'={alias}.ticker"
        "))"
    )


def install() -> None:
    """Install the policy in the publication implementation before consumers load."""
    from sentinel.feed import _publication_impl

    _publication_impl.visible_predicate = visible_predicate


__all__ = ["install", "visible_predicate"]
