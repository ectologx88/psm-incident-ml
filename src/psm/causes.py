"""Parse Form 2010 fields 18 (probable) and 19 (contributing) cause statements.

Two jobs, deliberately separated:

* :func:`segment_statements` splits a field into individual cause statements.
* :func:`candidate_category` pulls the *category-like prefix* from a statement
  without consulting any vocabulary list.

The second is what makes vocabulary **induction** honest. If the parser only
recognised a hard-coded category list, the induced vocabulary would be that
list reflected back — the classic way to "discover" what you already assumed.
So induction runs vocabulary-blind, and the observed distribution decides
whether a closed vocabulary exists at all.

Delimiter forms observed in the corpus (all must parse):

    Equipment failure: Inadequate preventive maintenance- <desc>
    Human Performance Error- Inadequate knowledge of equipment operation: <desc>
    Communication: Inadequate job instructions provided. <desc>
    • Equipment Failure – Inadequate Equipment Inspection: <desc>
    Management Systems:                     <- bare header, bullets beneath
    • Inadequate job procedures. <desc>
    1) Equipment Failure – Inadequate preventative maintenance/...
    The BSEE incident investigation team determined ...   <- free prose, no typing
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# Statement openers: bullet glyphs, or enumerators like "1)" / "2)." / "1.".
BULLET_RE = re.compile(r"^\s*(?:[••●▪·*]|[-–—](?=\s)|\d{1,2}\s*[).])\s*")

# Category/subcategory separators.
#
# An ASCII hyphen counts ONLY when followed by whitespace ("Human Performance
# Error- Inadequate knowledge..."). A hyphen with no space on either side is
# ordinary compounding, not a separator — an earlier `(?<=[a-z])-(?=[A-Z])`
# alternative split "Flexi-Coil hose" and invented a cause category "The Flexi".
# En/em dashes are separators regardless of spacing; they never compound here.
SEP_CLASS = r"[:–—]|(?<=[a-zA-Z])-(?=\s)"
SEP_RE = re.compile(SEP_CLASS)

# A category prefix is short and title-ish. Cap the length so a whole prose
# sentence ending in a dash cannot masquerade as a category.
MAX_CATEGORY_WORDS = 6
MAX_CATEGORY_CHARS = 60

CAUSE_STATUS = ("typed", "freetext", "absent_legitimate", "parse_failed")

# Field-label furniture that satisfies the category-prefix shape (short,
# title-ish, colon-separated) but is not a cause category. Confirmed leaking
# into field 18/19 body text via continuation-page markers and cross-field
# label bleed: report 030521-pdf (2003 EAC riser-insert failure, entirely
# free prose) matched "NOTE: ABB Vetco has redesigned..." and
# "LIST THE ADDITIONAL INFORMATION:" (field 20's own label) as typed
# categories. "LIST THE ..." is BSEE's own field-label phrasing (field 18 is
# literally "LIST THE PROBABLE CAUSE(S)"), so it generalises to any field's
# label bleeding into another field's body, not just field 20's.
FURNITURE_HEAD_RE = re.compile(r"^(?:NOTE|LIST\s+THE\b.*)$", re.IGNORECASE)


@dataclass
class CauseStatement:
    raw: str
    category: str | None
    subcategory: str | None
    description: str | None
    delimiter_form: str


# A font with no ToUnicode mapping renders its bullet glyph as "(cid:129)".
# The surrounding text is perfectly readable -- these are not broken documents,
# and the document-level guard in psm.extract correctly leaves them `ok`. But an
# unmapped glyph carries no information, and left in place it becomes the head of
# a "category" called "(cid". Normalised to a real bullet so the existing bullet
# handling picks it up, rather than stripped, because that is what it is.
CID_GLYPH_RE = re.compile(r"\(cid:\d+\)\s*")


def strip_cid_glyphs(text: str) -> str:
    """Replace unmapped-glyph tokens with a bullet."""
    return CID_GLYPH_RE.sub("\u2022 ", text or "")


def unwrap(text: str) -> list[str]:
    """Join PDF hard-wraps into logical statements.

    A new statement begins at a bullet/enumerator, or at a line whose prefix
    before a separator looks like a category. Everything else continues the
    previous line.
    """
    lines = [ln.strip() for ln in strip_cid_glyphs(text).splitlines() if ln.strip()]
    out: list[str] = []
    for ln in lines:
        starts_new = bool(BULLET_RE.match(ln))
        if not starts_new and out:
            m = SEP_RE.search(ln)
            if m and m.start() <= MAX_CATEGORY_CHARS:
                head = ln[: m.start()].strip()
                # Require title-ish: begins uppercase, few words, no terminal
                # punctuation mid-head.
                if (
                    head
                    and head[0].isupper()
                    and len(head.split()) <= MAX_CATEGORY_WORDS
                    and not head.endswith((".", ","))
                ):
                    starts_new = True
        if starts_new or not out:
            out.append(ln)
        else:
            out[-1] += " " + ln
    return out


def segment_statements(text: str) -> list[str]:
    """Split a field-18/19 body into individual cause statements."""
    if not text or not text.strip():
        return []
    statements = unwrap(text)

    # A bare header ("Management Systems:") followed by bullets distributes its
    # category over those bullets.
    resolved: list[str] = []
    pending_header: str | None = None
    for st in statements:
        body = BULLET_RE.sub("", st).strip()
        is_bullet = bool(BULLET_RE.match(st))
        m = SEP_RE.search(body)
        is_bare_header = bool(m) and not body[m.end():].strip()
        if is_bare_header and not is_bullet:
            pending_header = body[: m.start()].strip()
            continue
        if pending_header and is_bullet:
            resolved.append(f"{pending_header}: {body}")
            continue
        pending_header = None
        resolved.append(body)
    if pending_header and not resolved:
        resolved.append(pending_header)
    return [s for s in resolved if s]


def candidate_category(statement: str) -> tuple[str | None, str]:
    """Return ``(category_prefix, delimiter_form)`` without using a vocabulary.

    ``category_prefix`` is ``None`` when the statement does not look typed at
    all — which is itself the finding for free-text-era reports.
    """
    body = BULLET_RE.sub("", strip_cid_glyphs(statement)).strip()
    if not body:
        return None, "empty"
    m = SEP_RE.search(body)
    if not m or m.start() > MAX_CATEGORY_CHARS:
        return None, "untyped_prose"
    head = body[: m.start()].strip(" .–—-")
    if not head or not head[0].isalpha() or len(head.split()) > MAX_CATEGORY_WORDS:
        return None, "untyped_prose"
    if FURNITURE_HEAD_RE.match(head):
        return None, "furniture"
    sep = body[m.start(): m.end()]
    form = {":": "colon"}.get(sep, "dash")
    return head, form


def parse_statement(statement: str) -> CauseStatement:
    """Best-effort split into category / subcategory / description."""
    body = BULLET_RE.sub("", strip_cid_glyphs(statement)).strip()
    category, form = candidate_category(body)
    if category is None:
        return CauseStatement(body, None, None, body or None, form)

    m = SEP_RE.search(body)
    rest = body[m.end():].strip()

    # Subcategory runs to the next separator or the first sentence end.
    m2 = SEP_RE.search(rest)
    dot = re.search(r"(?<=[a-z])\.(?=\s|$)", rest)
    cut = min([p.start() for p in (m2, dot) if p] or [len(rest)])
    # Bullet chars are in the strip set because a cid-glyph bullet can sit
    # mid-statement, after the category separator, where the leading-bullet
    # rule above has already run and cannot reach it.
    sub = rest[:cut].strip(" .–—-•●▪·*") or None
    desc = rest[cut:].strip(" .:–—-•●▪·*") or None
    if sub and len(sub.split()) > 14:  # a whole sentence, not a subcategory
        sub, desc = None, rest
    return CauseStatement(body, category, sub, desc, form)


def normalise_category(name: str) -> str:
    """Fold surface variation so ``Equipment Failure`` == ``Equipment failure``."""
    s = name.strip().lower()
    s = re.sub(r"[\s_]+", " ", s)
    s = re.sub(r"[^a-z0-9 /]", "", s)
    return s.strip()


def classify_field(text: str | None) -> str:
    """Assign a ``cause_status``. ``absent_legitimate`` is not a parse failure.

    Blank fields 18/19 are sometimes genuinely correct — e.g. a third-party
    vessel allision outside BSEE jurisdiction. Conflating that with a parse
    failure sends you chasing bugs that do not exist.
    """
    if text is None:
        return "parse_failed"
    stripped = text.strip()
    if not stripped or stripped.upper() in {"N/A", "NA", "NONE", "N/A.", "NONE."}:
        return "absent_legitimate"
    statements = segment_statements(stripped)
    if not statements:
        return "absent_legitimate"
    if any(candidate_category(s)[0] for s in statements):
        return "typed"
    return "freetext"


def parse_field(text: str | None) -> dict:
    """Full parse of one cause field, including its status."""
    status = classify_field(text)
    statements = segment_statements(text or "") if text else []
    return {
        "cause_status": status,
        "statements": [asdict(parse_statement(s)) for s in statements],
    }
