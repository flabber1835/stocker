"""Source-backed RSAS terms; no strategy decisions or return targets."""
RSAS = {
    "security_id": "233957193007036874",
    "ticker": "RSAS",
    "original_event_session": "2006-09-15",
    "terms_session": "2006-09-18",
    "cash_per_share": "28.00",
    "sources": [
        "https://www.sec.gov/Archives/edgar/data/932064/000095013506004177/b614778ke8vk.htm",
        "https://www.sec.gov/Archives/edgar/data/790070/000119312506192225/d8k.htm",
        "https://www.sec.gov/Archives/edgar/data/790070/000119312506192225/dex992.htm",
    ],
}


def supplemented_terminals(rows):
    rows = list(rows)
    matches = [r for r in rows if r["ticker"] == "RSAS"
               or r["security_id"] == RSAS["security_id"]]
    if len(matches) != 1:
        raise ValueError("RSAS original event must occur exactly once")
    original = matches[0]
    required = {
        "security_id": RSAS["security_id"], "ticker": "RSAS",
        "effective_session": RSAS["original_event_session"],
        "kind": "CASH_MERGER", "cash_per_share": "",
        "disposition": "PIT_ACTION_INCOMPLETE:MISSING_CASH_PER_SHARE",
        "authority": "PIT_ACTIONS",
    }
    if any(original.get(k) != v for k, v in required.items()):
        raise ValueError("RSAS original event does not match retained authority")
    supplemental = {
        **original, "effective_session": RSAS["terms_session"],
        "cash_per_share": RSAS["cash_per_share"],
        "disposition": "EXACT_EVIDENCE", "authority": "SEC_COMPLETION_8K",
        "reference": "RSAS $28 cash; completed 2006-09-15; completion evidence "
                     "dated 2006-09-18; " + RSAS["sources"][1],
    }
    return rows + [supplemental]
