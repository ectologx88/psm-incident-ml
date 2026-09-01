"""Single source of truth for provenance tokens, fill colours, and the
column->token classification rule.

Token semantics (About-sheet legend must match):
  ""     cell is empty
  src    verbatim from a BSEE source document
  xw     deterministic crosswalk of a BSEE category (schema/crosswalk.yaml)
  llm    assigned by a language model, never ground truth
  gold   human-labelled ground truth (never written by code)
  syn    synthetic: deterministic hash-generated filler, no real referent
  key    constructed join identifier. The whole Incident Number column is
         built by this repo (AREA-BLOCK-YYYYMMDD-HHMM composites, some with
         UNKEYED-/collision hash parts); BSEE publishes no incident id.
         Classified BY COLUMN, not by string pattern -- pattern-matching
         INV-/SUP-/UNKEYED- substrings undercounts by ~850 cells.
  pseud  salted pseudonym of a real value (INV-/SUP- name tokens: stable
         privacy transforms of real people's names -- de-amplification,
         not fabrication; epistemically distinct from both src and key).
"""
from __future__ import annotations

TOKENS = frozenset({"", "src", "xw", "llm", "gold", "syn", "key", "pseud"})

# aRGB without the alpha byte; openpyxl reports "00"+this on round-trip.
FILL_COLORS = {
    "xw": "DDEBF7",     # blue
    "llm": "FFF2CC",    # amber
    "syn": "EDEDED",    # grey
    "key": "E2EFDA",    # green
    "pseud": "E4DFEC",  # lilac
}

UNSHADED = frozenset({"", "src"})

KEY_COLUMNS = frozenset({"Incident Number"})
PSEUD_COLUMNS = frozenset({
    "Investigation leader - Name",
    "Investigation Acceptor/Approver (Owner) - Name",
})


def provenance_row(
    row: dict,
    cols: list[str],
    key_columns: frozenset[str] = KEY_COLUMNS,
    pseud_columns: frozenset[str] = PSEUD_COLUMNS,
) -> dict[str, str]:
    """Base provenance for a row copied from source: empty cells stay "",
    constructed-identifier columns are `key`, pseudonym columns `pseud`,
    everything else `src`. Callers overwrite specific cells afterwards
    (xw/llm/syn) exactly as crosswalk.py already does."""
    out = {}
    for c in cols:
        if not (row.get(c) or "").strip():
            out[c] = ""
        elif c in key_columns:
            out[c] = "key"
        elif c in pseud_columns:
            out[c] = "pseud"
        else:
            out[c] = "src"
    return out
