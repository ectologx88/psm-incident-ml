"""Coordinate-aware layout reconstruction for MMS Form 2010 PDFs.

Why this module exists
----------------------
`page.extract_text()` on these forms returns text in *stream* order, not visual
order. On the form face that interleaves two columns into unreadable soup and
detaches checkbox ``X`` marks from their labels:

    1. OCCURRED
    X
    X STRUCTURAL DAMAGE
    DATE: 17-OCT-2020 TIME: 0445 HOURS CRANE

and in the narrative it can place a field label *after* its own content. Every
field assignment in this repo is therefore made from word bounding boxes, never
from ``extract_text()``.

The fix is cheap: bucket words into rows by their ``top`` coordinate, sort rows
top-to-bottom and words left-to-right within a row, and split the form face into
its two columns first. See ``docs/findings.md`` for the verification.
"""

from __future__ import annotations

from dataclasses import dataclass

# Row bucketing tolerance in points. Form 2010 body text is ~12pt leading, so
# 2.5 keeps genuinely different rows apart while tolerating baseline jitter
# within a row (observed: an "X" at top=250.7 beside its label at top=249.8).
# Maximum gap in points between two words for them to be on the same visual row.
# This is a GAP, not a bin width -- see _rows(). It was 2.5 when it meant a bin
# width (+/-1.25 from a centre); as a gap that value chains adjacent lines.
ROW_TOL = 1.5

# Maximum total baseline spread within one row, guarding against single-linkage
# chaining. Observed within-row spread on real form faces is 1.68pt.
ROW_SPAN_MAX = 2.0

# Search window for the form face's inter-column gutter, in points.
GUTTER_SEARCH = (240.0, 370.0)
GUTTER_MIN_WIDTH = 12.0
GUTTER_DEFAULT = 297.0

# A checkbox mark sits immediately left of its label on the same row.
CHECKBOX_MAX_GAP = 40.0
CHECKBOX_ROW_TOL = 4.0
CHECKBOX_MARKS = {"X", "x", "☒", "■", "▪"}


@dataclass(frozen=True)
class Line:
    """One visually reconstructed line of text."""

    page: int
    top: float
    x0: float
    text: str
    column: str  # "left", "right", or "full"


def _rows(words, tol: float = ROW_TOL):
    """Group words into visual rows by clustering on ``top``.

    An earlier version bucketed on ``round(top / tol)``. That is a fixed bin
    EDGE, not a tolerance: two words on the same baseline land in different rows
    whenever an edge falls between them, however close they are. Measured across
    120 sampled PDFs it produced **47.6% more rows than the page actually has**,
    affecting 119 of 120 documents -- and the damage was not cosmetic. It split
    ``BLOCK:`` (top 308.8) from its value ``25`` (top 308.3), so a downstream
    regex read the next field's ordinal instead; it split ``3.`` from
    ``OPERATOR/CONTRACTOR``, so form-revision detection saw an absent field 3 and
    misclassified 32 revision-B documents as revision A.

    Single linkage on the gap is the right shape, but the tolerance had to shrink
    with it. As a bin width, 2.5 meant +/-1.25 either side of a centre; as a gap
    it means "chain anything within 2.5pt", which is much looser and does chain:
    at tol 2.0 the within-row spread on a sampled form face jumps to 3.36pt, i.e.
    two distinct lines merged. The observed gap distribution is bimodal -- 146 of
    222 consecutive gaps are under 1pt (same-baseline jitter), 62 exceed 2.5pt
    (genuine line breaks), and only 14 fall between -- so 1.5 sits in the empty
    middle with room either side.

    Single linkage alone is not sufficient either: a ladder of words each within
    the tolerance of the last chains without limit, so six words stepping 1.4pt
    apart merge across 7pt into one "row". Real form faces do not exhibit that
    ladder -- observed within-row spread is 1.68pt -- but nothing in the
    algorithm prevented it, so a row is also capped at ROW_SPAN_MAX from its
    first word. A text line's words share a baseline; they do not drift.
    """
    ordered = sorted(words, key=lambda w: w["top"])
    row: list = []
    for w in ordered:
        if row and w["top"] - row[-1]["top"] <= tol and w["top"] - row[0]["top"] <= ROW_SPAN_MAX:
            row.append(w)
        else:
            if row:
                yield sorted(row, key=lambda w: w["x0"])
            row = [w]
    if row:
        yield sorted(row, key=lambda w: w["x0"])


# A candidate gutter must be uncrossed by this fraction of the page's rows, and
# both sides must carry at least MIN_COLUMN_ROWS rows. Without these guards a
# short paragraph on a narrative page yields a false gutter that shreds prose.
GUTTER_CLEAR_FRACTION = 0.85
MIN_COLUMN_ROWS = 3


def find_gutter(words) -> float | None:
    """Locate the vertical whitespace band separating the form's two columns.

    Returns the x coordinate of the gutter centre, or ``None`` when the page is
    single-column.

    Detected per page rather than hard-coded, because the form face and the
    final admin block are two-column while the narrative pages between them are
    not, and older reports shift the column boundary. The test is *row-aware*:
    a real gutter is one that almost no row crosses, which distinguishes a
    column break from an accidental gap in ragged prose.
    """
    lo, hi = GUTTER_SEARCH
    rows = list(_rows(words))
    if len(rows) < 2 * MIN_COLUMN_ROWS:
        return None

    # Which x positions look like gutter, by the row-crossing test alone.
    ok: list[int] = []
    for x in range(int(lo), int(hi) + 1):
        crossed = sum(1 for r in rows if any(w["x0"] < x < w["x1"] for w in r))
        if crossed / len(rows) > (1.0 - GUTTER_CLEAR_FRACTION):
            continue
        left_rows = sum(1 for r in rows if any(w["x1"] <= x for w in r))
        right_rows = sum(1 for r in rows if any(w["x0"] >= x for w in r))
        if left_rows < MIN_COLUMN_ROWS or right_rows < MIN_COLUMN_ROWS:
            continue
        ok.append(x)

    if not ok:
        return None

    # Widest contiguous run of qualifying positions is the gutter. Measuring the
    # band with the *same* test that selected it matters: an earlier version
    # widened using page-wide pixel occupancy, a stricter and contradictory
    # criterion, so every page came back single-column.
    best_len, best_span = 0, None
    start = prev = ok[0]
    for x in ok[1:] + [None]:
        if x is not None and x == prev + 1:
            prev = x
            continue
        if prev - start + 1 > best_len:
            best_len, best_span = prev - start + 1, (start, prev)
        if x is not None:
            start = prev = x

    if best_span is None or best_len < GUTTER_MIN_WIDTH:
        return None
    return (best_span[0] + best_span[1]) / 2.0


def page_lines(page, page_index: int, force_single_column: bool = False) -> list[Line]:
    """Reconstruct one page's lines in visual reading order.

    Two-column pages are emitted as the full left column followed by the full
    right column, which is how a human reads the form face.
    """
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    if not words:
        return []

    gutter = None if force_single_column else find_gutter(words)
    if gutter is None:
        out = []
        for row in _rows(words):
            out.append(
                Line(page_index, row[0]["top"], row[0]["x0"],
                     " ".join(w["text"] for w in row), "full")
            )
        return out

    left = [w for w in words if w["x1"] <= gutter]
    right = [w for w in words if w["x1"] > gutter]
    out = []
    for name, group in (("left", left), ("right", right)):
        for row in _rows(group):
            out.append(
                Line(page_index, row[0]["top"], row[0]["x0"],
                     " ".join(w["text"] for w in row), name)
            )
    return out


def document_lines(pdf) -> list[Line]:
    """Visual-order lines for a whole document.

    Column detection runs per page rather than by page index: the form face is
    two-column, the narrative pages are not, and the closing admin block
    (fields 25-30) is two-column again. Assuming "page 0 only" silently merged
    ``25. ... 28. ...`` onto one line and lost fields 26, 27 and 29.
    """
    lines: list[Line] = []
    for i, page in enumerate(pdf.pages):
        lines.extend(page_lines(page, i))
    return lines


def checkbox_labels(page, page_index: int = 0) -> list[tuple[str, float, float]]:
    """Pair checkbox marks with the label immediately to their right.

    Returns ``(label, x, top)`` per ticked box. The form uses a literal "X"
    glyph rather than an AcroForm widget, so this is positional: take the words
    starting within ``CHECKBOX_MAX_GAP`` points to the right of the mark, on the
    same row.
    """
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    marks = [w for w in words if w["text"].strip() in CHECKBOX_MARKS]
    out = []
    for m in marks:
        same_row = [
            w for w in words
            if abs(w["top"] - m["top"]) <= CHECKBOX_ROW_TOL
            and w["x0"] > m["x1"]
            and w["x0"] - m["x1"] <= CHECKBOX_MAX_GAP
            and w is not m
        ]
        if not same_row:
            continue
        same_row.sort(key=lambda w: w["x0"])
        # Walk right while words stay adjacent, to capture multi-word labels
        # such as "DAMAGED/DISABLED SAFETY SYS.".
        label = [same_row[0]]
        for w in same_row[1:]:
            if w["x0"] - label[-1]["x1"] <= 12.0:
                label.append(w)
            else:
                break
        out.append((" ".join(w["text"] for w in label), m["x0"], m["top"]))
    return out
