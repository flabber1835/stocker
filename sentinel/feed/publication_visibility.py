"""Publication visibility policy for append-only SEP retirement generations."""
from __future__ import annotations


def generation_visible_predicate(alias: str = "b") -> str:
    """Whether the physical row's owning generation has been published."""
    return (
        f"({alias}.last_written_run_id IS NULL"
        f" OR EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
        f"            WHERE p.run_id = {alias}.last_written_run_id))"
    )


def retired_predicate(alias: str = "b") -> str:
    """Whether this published physical SEP generation was tombstoned later.

    A new unpublished writer generation is a candidate reappearance, so its
    predecessor values remain available to the existing chunked ingest path.
    Reader visibility still requires that candidate to be published.
    """
    published = generation_visible_predicate(alias)
    return (
        f"({published} AND EXISTS ("
        " SELECT 1 FROM sentinel_corpus_publications retirement"
        " CROSS JOIN LATERAL jsonb_array_elements("
        "   CASE WHEN jsonb_typeof("
        "       retirement.evidence #> '{source_retirement,keys}') = 'array'"
        "     THEN retirement.evidence #> '{source_retirement,keys}'"
        "     ELSE '[]'::jsonb END) retired_key"
        " WHERE retirement.evidence->>'kind'='sep_source_retirement'"
        f"   AND retirement.version > COALESCE((SELECT MIN(base.version)"
        "       FROM sentinel_corpus_publications base"
        f"       WHERE base.run_id={alias}.last_written_run_id), 0)"
        f"   AND retired_key->>'security_id'={alias}.security_id"
        f"   AND retired_key->>'session'={alias}.session::text"
        f"   AND retired_key->>'ticker'={alias}.ticker"
        "))"
    )


def visible_predicate(alias: str = "b", *, sep_retirements: bool = True) -> str:
    """Return the canonical SQL predicate for a publication-visible bar row.

    Physical presence is insufficient: a bar must belong to a published ingest
    generation (or predate run provenance), and no later published SEP retirement
    generation may tombstone its exact ``security_id/session/ticker`` key.

    Retirement keys are append-only evidence in
    ``sentinel_corpus_publications.evidence.source_retirement.keys``. A later bar
    generation naturally supersedes an older tombstone because the comparison is
    against the bar generation's publication version.
    """
    published = generation_visible_predicate(alias)
    if not sep_retirements:
        return published
    return f"({published} AND NOT {retired_predicate(alias)})"


def install() -> None:
    """Install the policy in the publication implementation before consumers load."""
    from sentinel.feed import _publication_impl

    _publication_impl.visible_predicate = visible_predicate


__all__ = ["generation_visible_predicate", "install", "retired_predicate", "visible_predicate"]
