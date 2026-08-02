"""Harvest the URL manifest of BSEE offshore incident investigation report PDFs.

Entry point::

    uv run python -m psm.harvest            # normal run (uses on-disk HTML cache)
    uv run python -m psm.harvest --refresh  # re-fetch every index page from bsee.gov
    uv run python -m psm.harvest --report   # print distributions after writing

Writes ``data/manifest.csv``. **Does not download any PDF.** ``src_sha256`` is
emitted empty on purpose; ``psm.fetch`` fills it after download.

--------------------------------------------------------------------------
What counts as an "investigation report PDF"
--------------------------------------------------------------------------
A page-wide ``grep 'href=.*\\.pdf'`` is *not* the definition used here, because
it cannot tell an investigation report from a site-nav PDF. The rule is
structural and checkable by a stranger:

  district : the ``<a href>`` must sit inside a **data row of a year table**
             in ``<main>`` on one of the two district index pages. Every year
             table has the header row
             ``Date Occurred | Military Time | Lease Number | Area/Block | Accident Type``.
             The report link lives in the first cell (``Date Occurred``).
  panel    : the ``<a href>`` must be the attachment on a
             ``/panel-investigation/...`` detail page that is itself linked
             from the paginated panel listing table.

Rows on the district index whose first cell links to a Drupal *node alias*
rather than a PDF are followed one hop to that node page and the attachment
there is taken (``src_detail_page`` records the hop).

--------------------------------------------------------------------------
Four index sources (not two)
--------------------------------------------------------------------------
``district-investigation-reports``          year tables 2014-2026
``district-investigation-reports-archive``   year tables 2003-2013 (reached via
                                             the "View Archive" link)
``panel-investigation-reports?page=0..N``    paginated listing -> detail pages

--------------------------------------------------------------------------
URL canonicalisation
--------------------------------------------------------------------------
Some published hrefs point at hosts that are not the live site
(``bsee_prod.opengov.ibmcloud.com`` -- note the underscore, illegal in DNS --
``connect.bsee.gov``, and two leaked Acquia staging hosts). For those, and only
those, the host is swapped for ``www.bsee.gov`` **with the path preserved**.
The original href is always kept verbatim in ``src_url_published`` and the
rewrite is flagged in ``src_url_canonicalised``; nothing is silently repaired.

Root-relative and bare-relative (no leading slash) hrefs are resolved against
``https://www.bsee.gov/`` -- note that ``urljoin`` against an index-page URL
*with a path* mangles the bare-relative form, so the site root is used as base.

--------------------------------------------------------------------------
Filename parsing: known limits
--------------------------------------------------------------------------
``2010`` in a BSEE filename is normally the **MMS Form 2010 number**, not a
year (``EV2010``, ``EV2010R``, ``2010_Report``, trailing ``-2010``). The parser
therefore never falls back to a bare 4-digit year: a date is only accepted from
an explicit date *token*. Filenames with no date token get an empty date and a
non-empty ``src_parse_note``. Rows are never dropped and values are never
guessed.

Filename-derived ``src_area``/``src_block`` are a convenience only. The
authoritative area/block is Form 2010 field 4 inside the PDF; the index table's
verbatim ``Area/Block`` cell is carried alongside as
``src_index_area_block`` for cross-checking.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

SITE_ROOT = "https://www.bsee.gov/"

DISTRICT_URL = (
    "https://www.bsee.gov/what-we-do/incident-investigations/"
    "offshore-incident-investigations/district-investigation-reports"
)
DISTRICT_ARCHIVE_URL = DISTRICT_URL + "/district-investigation-reports-archive"
PANEL_URL = (
    "https://www.bsee.gov/what-we-do/incident-investigations/"
    "offshore-incident-investigations/panel-investigation-reports"
)

USER_AGENT = (
    "psm-incident-ml/0.1 (public research dataset build; "
    "https://github.com/ ; contact via repository issues)"
)
REQUEST_DELAY_S = 1.5
MAX_PANEL_PAGES = 20  # guard rail; the listing is 3 pages as of 2026-08

#: Hosts that appear in published hrefs but are not the live site. Two are
#: Acquia staging hosts that leaked into content; ``bsee_prod.opengov...``
#: cannot even be resolved (an underscore is illegal in a DNS label).
#: The fix is a host swap that *preserves the path* -- verified 2026-08-02 by
#: HEAD request: the as-published URLs fail, the host-swapped ones return 200,
#: and a basename-only rewrite would 404 for the ``memos/`` and
#: ``safety-alerts/`` subfolders on the panel side.
DEAD_HOSTS = frozenset(
    {
        "bsee_prod.opengov.ibmcloud.com",
        "connect.bsee.gov",
        "doibsee.prod.acquia-sites.com",
        "doibseetest.prod.acquia-sites.com",
    }
)
LIVE_HOST = "www.bsee.gov"

#: OCS area abbreviations, derived empirically from the ``Area/Block`` column of
#: every year table on both district index pages (2003-2026). Kept as observed,
#: including ``EL`` -- which is a source-data typo for ``EI`` (capital-E
#: lowercase-L) that appears verbatim on the index page. Source data stays dirty.
AREA_CODES = frozenset(
    [
        "AC",
        "AS",
        "AT",
        "BA",
        "BM",
        "BS",
        "DC",
        "EB",
        "EC",
        "EI",
        "EL",
        "EW",
        "GA",
        "GB",
        "GC",
        "GI",
        "HI",
        "HIA",
        "KC",
        "LA",
        "LB",
        "MC",
        "MI",
        "MO",
        "MP",
        "MU",
        "PL",
        "PN",
        "SE",
        "SM",
        "SP",
        "SS",
        "ST",
        "VK",
        "VR",
        "WC",
        "WD",
        "WR",
    ]
)

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MON_ALT = "|".join(_MONTHS)

# Date token patterns, tried in order. Every pattern requires day+month
# structure -- a bare 4-digit year is never accepted (see module docstring).
_SEP = r"[-_. ]*"
_YEAR = r"20\d{2}|\d{2}"  # 4-digit years must start with 20; else a 2-digit year
DATE_PATTERNS: tuple[tuple[str, str], ...] = (
    # 24-May-26 / 05_may_2016 / 31mar19 / 7july2020 / 18-APR-2026 / 17_MAR_2025
    (
        "dmy_name",
        rf"(?<![0-9])(?P<d>\d{{1,2}}){_SEP}(?P<mon>{_MON_ALT})[a-z]*{_SEP}(?P<y>{_YEAR})(?![0-9])",
    ),
    # may-24-2026 (month first)
    (
        "mdy_name",
        rf"(?<![a-z0-9])(?P<mon>{_MON_ALT})[a-z]*{_SEP}(?P<d>\d{{1,2}}){_SEP}(?P<y>{_YEAR})(?![0-9])",
    ),
    # 20170911  (YYYYMMDD, no separators) -- must precede the MMDDYYYY pattern
    (
        "yyyymmdd",
        r"(?<![0-9])(?P<y>20\d{2})(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])(?![0-9])",
    ),
    # 09112019  (MMDDYYYY, no separators)
    (
        "mmddyyyy",
        r"(?<![0-9])(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])(?P<y>20\d{2})(?![0-9])",
    ),
    # 12-20-2013 / 3.15.2005
    ("mm_dd_yyyy", r"(?<![0-9])(?P<m>\d{1,2})[-_.](?P<d>\d{1,2})[-_.](?P<y>20\d{2})(?![0-9])"),
    # 05-26-11 / 12-18-11 -- US month-first order, matching the index tables'
    # own MM-DD-YYYY "Date Occurred" column. Both halves are range-checked so a
    # DD-MM-YY reading would have to be indistinguishable to slip through.
    (
        "mm_dd_yy",
        r"(?<![0-9])(?P<m>0[1-9]|1[0-2])[-_.](?P<d>0[1-9]|[12]\d|3[01])[-_.](?P<y>\d{2})(?![0-9])",
    ),
)

#: Whole-stem archive form: YYMMDD plus an optional dedupe letter, e.g.
#: ``091219a-pdf``, ``080326-pdf``, ``100227-pdf``. Verified against the index
#: table's own ``Date Occurred`` cell: 462 of 463 such filenames match exactly.
ARCHIVE_YYMMDD_RE = re.compile(
    r"^(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?P<seq>[a-z])?(?:-pdf)?$", re.IGNORECASE
)

#: Matches ``redacted``, ``sanitized``/``sanitised`` and the source's own
#: misspellings (``santized``, ``santitized``) -- all appear in real filenames.
REDACTION_RE = re.compile(r"redact|san\w*i[sz]ed", re.IGNORECASE)

#: Trailing Drupal duplicate-upload / revision markers, stripped right-to-left.
#: The numeric form is capped at two digits so a trailing ``_2016`` (a date, not
#: a duplicate counter) is never eaten.
VARIANT_RE = re.compile(r"(?:\s*\(\d{1,2}\)|[_-]v\d{1,2}|_\d{1,2})\s*$", re.IGNORECASE)

#: Tokens that are never part of an operator name.
NOISE_TOKENS = frozenset(
    [
        "pdf",
        "report",
        "reports",
        "final",
        "draft",
        "copy",
        "redacted",
        "sanitized",
        "sanitised",
        "santized",
        "ev2010",
        "ev2010r",
        "ev2010rr",
        "2010",
        "form",
        "rev",
        "revised",
        "v2",
        "accident",
        "acc",
        "inc",
        "incident",
        "a",
    ]
)

MANIFEST_COLUMNS = [
    "src_report_type",
    "src_index_page",
    "src_index_year",
    "src_detail_page",
    "src_attachment_index",
    "src_url_published",
    "src_url",
    "src_url_display",
    "src_url_canonicalised",
    "src_filename",
    "src_area",
    "src_block",
    "src_operator",
    "src_date_text",
    "src_date_parsed",
    "src_year",
    "src_is_redacted",
    "src_variant_suffix",
    "src_parse_note",
    "src_index_date_occurred",
    "src_index_time",
    "src_index_lease_number",
    "src_index_area_block",
    "src_index_accident_type",
    "src_index_row_count",
    "src_panel_number",
    "src_panel_title",
    "src_panel_publication_date",
    "src_sha256",
]

#: Structural oddities noticed while scraping. Logged, never silently repaired.
ANOMALIES: list[str] = []

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "data" / "manifest.csv"
CACHE_DIR = REPO_ROOT / "data" / "interim" / "harvest_cache"


# --------------------------------------------------------------------------
# Filename parsing
# --------------------------------------------------------------------------


@dataclass
class ParsedName:
    """Result of :func:`parse_filename`. Empty strings mean "not recovered"."""

    area: str = ""
    block: str = ""
    operator: str = ""
    date_text: str = ""
    date_parsed: str = ""
    year: str = ""
    is_redacted: bool = False
    variant_suffix: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def parse_note(self) -> str:
        return ";".join(self.notes)


def _expand_year(raw: str) -> int:
    """2-digit years are 20xx. Every BSEE district report post-dates 2000."""
    return int(raw) if len(raw) == 4 else 2000 + int(raw)


def _find_date_tokens(stem: str) -> list[tuple[str, str, date]]:
    """Return ``[(pattern_name, matched_text, date)]`` for every date token found.

    Ordered by position in *stem*. Overlapping hits from different patterns are
    de-duplicated by span.
    """
    hits: dict[tuple[int, int], tuple[str, str, date]] = {}
    for name, pattern in DATE_PATTERNS:
        for m in re.finditer(pattern, stem, re.IGNORECASE):
            gd = m.groupdict()
            month = _MONTHS[gd["mon"][:3].lower()] if gd.get("mon") else int(gd["m"])
            try:
                value = date(_expand_year(gd["y"]), month, int(gd["d"]))
            except ValueError:
                continue
            span = (m.start(), m.end())
            if any(s <= span[0] < e or s < span[1] <= e for s, e in hits):
                continue
            hits[span] = (name, m.group(0), value)
    return [hits[k] for k in sorted(hits)]


def _strip_variants(stem: str) -> tuple[str, str]:
    """Strip trailing Drupal duplicate/revision markers. Returns (stem, suffix)."""
    suffixes: list[str] = []
    while True:
        m = VARIANT_RE.search(stem)
        if not m:
            break
        suffixes.insert(0, m.group(0).strip())
        stem = stem[: m.start()].rstrip(" -_")
    return stem, "".join(suffixes)


def _tokenise(text: str) -> list[str]:
    return [t for t in re.split(r"[^0-9A-Za-z&]+", text) if t]


def _find_area_block(tokens: list[str]) -> tuple[int, int, str, str]:
    """Locate the area/block run in *tokens*.

    Returns ``(start_index, end_index_exclusive, area, block)``; ``area`` is
    empty when no token maps to a known OCS area abbreviation.

    Handles the three shapes seen in the wild:
      ``['mp', '298']``            -> MP / 298
      ``['sm58']``                 -> SM / 58        (area and block joined)
      ``['hi', 'a', '573', 'b']``  -> HI / A 573 B   (platform letter either side)
    """
    for i, tok in enumerate(tokens):
        upper = tok.upper()
        joined = re.fullmatch(r"([A-Z]{2,3})(\d{1,4})", upper)
        if upper in AREA_CODES:
            area, j, lead = upper, i + 1, ""
            # optional platform letter before the block number: HI A 573
            if (
                j < len(tokens)
                and re.fullmatch(r"[A-Za-z]", tokens[j])
                and (j + 1 < len(tokens) and tokens[j + 1].isdigit())
            ):
                lead = tokens[j].upper()
                j += 1
            if j >= len(tokens) or not re.fullmatch(r"\d{1,4}[A-Za-z]?", tokens[j]):
                continue
            block_parts = ([lead] if lead else []) + [tokens[j].upper()]
            j += 1
        elif joined and joined.group(1) in AREA_CODES:
            area = joined.group(1)
            block_parts = [joined.group(2)]
            j = i + 1
        else:
            continue
        # optional trailing platform letter: 472 A / 27 B
        if j < len(tokens) and re.fullmatch(r"[A-Za-z]", tokens[j]):
            block_parts.append(tokens[j].upper())
            j += 1
        return i, j, area, " ".join(block_parts)
    return -1, -1, "", ""


def parse_filename(filename: str) -> ParsedName:
    """Parse a BSEE report filename into area / block / operator / date.

    Deliberately conservative: anything not confidently recoverable is left
    empty and explained in :attr:`ParsedName.notes`. Never raises.

    >>> p = parse_filename("MP 298 Cantium 24-May-26.pdf")
    >>> (p.area, p.block, p.operator, p.date_parsed)
    ('MP', '298', 'Cantium', '2026-05-24')
    """
    out = ParsedName()
    stem = re.sub(r"\.pdf\s*$", "", filename.strip(), flags=re.IGNORECASE).strip()
    if not stem:
        out.notes.append("empty_filename")
        return out

    out.is_redacted = bool(REDACTION_RE.search(stem))
    stem, out.variant_suffix = _strip_variants(stem)

    # --- date -------------------------------------------------------------
    date_span: tuple[int, int] | None = None
    archive = ARCHIVE_YYMMDD_RE.fullmatch(stem)
    if archive:
        try:
            value = date(
                _expand_year(archive.group("y")),
                int(archive.group("m")),
                int(archive.group("d")),
            )
        except ValueError:
            value = None
        if value is not None:
            out.date_text = stem
            out.date_parsed = value.isoformat()
            out.year = str(value.year)
            out.notes.append("archive_yymmdd_filename")
            out.notes.append("no_area_block_in_filename")
            return out
        out.notes.append("archive_yymmdd_invalid")
    else:
        hits = _find_date_tokens(stem)
        if hits:
            if len(hits) > 1:
                out.notes.append(f"multiple_date_tokens:{len(hits)}")
            _pattern_name, text, value = hits[0]
            out.date_text = text
            out.date_parsed = value.isoformat()
            out.year = str(value.year)
            date_span = (stem.index(text), stem.index(text) + len(text))
        else:
            out.notes.append("no_date_token")

    # --- area / block / operator -----------------------------------------
    masked = stem if date_span is None else stem[: date_span[0]] + " | " + stem[date_span[1] :]
    tokens = _tokenise(masked)
    start, end, area, block = _find_area_block(tokens)
    if not area:
        out.notes.append("no_area_block_in_filename")
        operator_tokens = tokens
    else:
        out.area, out.block = area, block
        operator_tokens = tokens[:start] + tokens[end:]

    operator = " ".join(
        t for t in operator_tokens if t.lower() not in NOISE_TOKENS and not t.isdigit()
    ).strip()
    out.operator = operator
    if not operator:
        out.notes.append("no_operator_in_filename")
    return out


# --------------------------------------------------------------------------
# URL handling
# --------------------------------------------------------------------------


def resolve_url(href: str) -> tuple[str, str, bool]:
    """Return ``(fetch_url, display_url, canonicalised)`` for a published href.

    ``fetch_url`` is absolute and percent-encoded; ``display_url`` is the same
    URL percent-decoded for human reading. ``canonicalised`` is True when the
    published host was one of :data:`DEAD_HOSTS` and was swapped for the live
    host, path preserved.

    Bare-relative hrefs (``sites/bsee.gov/files/x.pdf``, no leading slash) are
    resolved against the *site root*, never against the index page URL.
    """
    href = href.strip()
    absolute = urllib.parse.urljoin(SITE_ROOT, href)
    parts = urllib.parse.urlsplit(absolute)
    canonicalised = False
    if parts.netloc in DEAD_HOSTS:
        absolute = urllib.parse.urlunsplit(
            ("https", LIVE_HOST, parts.path, parts.query, parts.fragment)
        )
        canonicalised = True
    display = urllib.parse.unquote(absolute)
    # Re-encode the display form to guarantee the fetch form is request-safe
    # while leaving already-encoded input untouched.
    p = urllib.parse.urlsplit(display)
    fetch = urllib.parse.urlunsplit(
        (p.scheme, p.netloc, urllib.parse.quote(p.path, safe="/%:@&=+$,~"), p.query, p.fragment)
    )
    return fetch, display, canonicalised


def url_filename(display_url: str) -> str:
    """Decoded basename, verbatim -- spaces, ampersands and all."""
    return urllib.parse.urlsplit(display_url).path.rsplit("/", 1)[-1]


# --------------------------------------------------------------------------
# Fetching (cached, rate-limited)
# --------------------------------------------------------------------------


class Fetcher:
    """Rate-limited HTML fetcher with an on-disk cache under data/interim/."""

    def __init__(self, *, refresh: bool = False, delay: float = REQUEST_DELAY_S) -> None:
        self.refresh = refresh
        self.delay = delay
        self._last = 0.0
        self._session = None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url: str) -> Path:
        return CACHE_DIR / f"{hashlib.sha1(url.encode()).hexdigest()}.html"

    def get(self, url: str) -> str:
        path = self._cache_path(url)
        if path.exists() and not self.refresh:
            return path.read_text(encoding="utf-8", errors="replace")
        import requests  # imported lazily so tests need no network stack

        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": USER_AGENT})
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        resp = self._session.get(url, timeout=60)
        self._last = time.monotonic()
        resp.raise_for_status()
        path.write_text(resp.text, encoding="utf-8")
        return resp.text


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# --------------------------------------------------------------------------
# District index scraping
# --------------------------------------------------------------------------

DISTRICT_HEADER_FIRST_CELL = "date occurred"


def _cells(tr) -> list[str]:
    return [td.get_text(" ", strip=True).replace("\xa0", " ") for td in tr.find_all(["td", "th"])]


def _pdf_links(node) -> list[str]:
    return [a["href"] for a in node.find_all("a", href=True) if ".pdf" in a["href"].lower()]


def scrape_district(html: str, index_page: str, fetcher: Fetcher) -> list[dict]:
    """Extract one row per report link from a district index page.

    Handles both index layouts: one ``<table>`` per year preceded by an ``<h2>``
    year heading (current page), and a single ``<table>`` with one-cell year
    separator rows (archive page).
    """
    rows: list[dict] = []
    main = soup(html).find("main")
    if main is None:
        return rows

    for table in main.find_all("table"):
        heading = table.find_previous(["h2", "h3"])
        table_year = heading.get_text(strip=True) if heading else ""
        current_year = table_year if re.fullmatch(r"20\d{2}", table_year) else ""
        for tr in table.find_all("tr"):
            cells = _cells(tr)
            if len(cells) == 1 and re.fullmatch(r"20\d{2}", cells[0]):
                current_year = cells[0]  # archive-style year separator row
                continue
            if not cells or cells[0].strip().lower() == DISTRICT_HEADER_FIRST_CELL:
                continue
            hrefs = _pdf_links(tr)
            detail_page = ""
            if not hrefs:
                node_links = [
                    a["href"]
                    for a in tr.find_all("a", href=True)
                    if ".pdf" not in a["href"].lower()
                ]
                if not node_links:
                    continue  # genuinely unlinked row -- reported, not emitted
                detail_page = urllib.parse.urljoin(SITE_ROOT, node_links[0])
                hrefs = _pdf_links(soup(fetcher.get(detail_page)).find("main"))
                if not hrefs:
                    continue
            base = {
                "src_report_type": "district",
                "src_index_page": index_page,
                "src_index_year": current_year,
                "src_detail_page": detail_page,
                "src_index_date_occurred": cells[0] if len(cells) > 0 else "",
                "src_index_time": cells[1] if len(cells) > 1 else "",
                "src_index_lease_number": cells[2] if len(cells) > 2 else "",
                "src_index_area_block": cells[3] if len(cells) > 3 else "",
                "src_index_accident_type": cells[4] if len(cells) > 4 else "",
            }
            for position, href in enumerate(hrefs):
                rows.append(
                    {**base, "src_attachment_index": str(position), "src_url_published": href}
                )
    return rows


def district_unlinked_rows(html: str) -> list[list[str]]:
    """Index rows that list an incident but carry no link at all. Reported, not emitted."""
    out: list[list[str]] = []
    main = soup(html).find("main")
    if main is None:
        return out
    for table in main.find_all("table"):
        for tr in table.find_all("tr"):
            cells = _cells(tr)
            if not cells or len(cells) == 1:
                continue
            if cells[0].strip().lower() == DISTRICT_HEADER_FIRST_CELL:
                continue
            if not tr.find_all("a", href=True):
                out.append(cells)
    return out


# --------------------------------------------------------------------------
# Panel index scraping
# --------------------------------------------------------------------------


def _panel_listing_rows(html: str) -> list[dict]:
    main = soup(html).find("main")
    table = main.find("table") if main else None
    if table is None:
        return []
    out = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        link = tds[0].find("a", href=True)
        if not link:
            continue
        out.append(
            {
                "number": link.get_text(strip=True),
                "detail": urllib.parse.urljoin(SITE_ROOT, link["href"]),
                "block": tds[1].get_text(" ", strip=True),
                "title": tds[2].get_text(" ", strip=True),
            }
        )
    return out


def _field_value(main, field_name: str) -> str:
    node = main.find(class_=re.compile(rf"field--name-{re.escape(field_name)}(\s|$)"))
    if node is None:
        return ""
    item = node.find(class_="field__item")
    return (item or node).get_text(" ", strip=True)


def scrape_panel(fetcher: Fetcher) -> list[dict]:
    """Walk the paginated panel listing, then one detail page per report."""
    listing: list[dict] = []
    seen_details: set[str] = set()
    for page in range(MAX_PANEL_PAGES):
        url = f"{PANEL_URL}?page={page}"
        entries = _panel_listing_rows(fetcher.get(url))
        fresh = [e for e in entries if e["detail"] not in seen_details]
        if not fresh:
            break
        for e in fresh:
            seen_details.add(e["detail"])
            e["index_page"] = url
        listing.extend(fresh)

    rows: list[dict] = []
    for entry in listing:
        main = soup(fetcher.get(entry["detail"])).find("main")
        if main is None or not _pdf_links(main):
            ANOMALIES.append(f"panel listing entry has no PDF attachment: {entry['detail']}")
            continue
        for position, href in enumerate(_pdf_links(main)):
            rows.append(
                {
                    "src_report_type": "panel",
                    "src_index_page": entry["index_page"],
                    "src_index_year": "",
                    "src_detail_page": entry["detail"],
                    "src_attachment_index": str(position),
                    "src_url_published": href,
                    "src_index_area_block": entry["block"],
                    "src_panel_number": entry["number"],
                    "src_panel_title": entry["title"],
                    "src_panel_publication_date": _field_value(main, "field-year-created"),
                }
            )
    return rows


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def build_rows(fetcher: Fetcher) -> list[dict]:
    raw: list[dict] = []
    for url in (DISTRICT_URL, DISTRICT_ARCHIVE_URL):
        raw.extend(scrape_district(fetcher.get(url), url, fetcher))
    raw.extend(scrape_panel(fetcher))

    # One PDF is occasionally linked from several index rows (BSEE lists one
    # report against two incidents). The manifest is keyed on the file, so the
    # first row's metadata is kept and the collision is counted rather than
    # hidden -- see src_index_row_count.
    link_counts = Counter(resolve_url(item["src_url_published"])[0] for item in raw)
    for url, n in link_counts.items():
        if n > 1:
            ANOMALIES.append(f"{n} index rows link the same file: {url}")

    rows: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        fetch, display, canonicalised = resolve_url(item["src_url_published"])
        if fetch in seen:
            continue  # same file linked from more than one index row
        seen.add(fetch)
        filename = url_filename(display)
        parsed = parse_filename(filename)
        row = {col: "" for col in MANIFEST_COLUMNS}
        row.update(item)
        row.update(
            {
                "src_url": fetch,
                "src_url_display": display,
                "src_url_canonicalised": "true" if canonicalised else "false",
                "src_filename": filename,
                "src_area": parsed.area,
                "src_block": parsed.block,
                "src_operator": parsed.operator,
                "src_date_text": parsed.date_text,
                "src_date_parsed": parsed.date_parsed,
                "src_year": parsed.year,
                "src_is_redacted": "true" if parsed.is_redacted else "false",
                "src_variant_suffix": parsed.variant_suffix,
                "src_parse_note": parsed.parse_note,
                "src_index_row_count": str(link_counts[fetch]),
                "src_sha256": "",
            }
        )
        rows.append({col: row.get(col, "") for col in MANIFEST_COLUMNS})

    rows.sort(key=lambda r: (r["src_report_type"], r["src_url"]))
    return rows


def write_manifest(rows: list[dict], path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def report(rows: list[dict], unlinked: dict[str, int] | None = None) -> str:
    lines: list[str] = [f"rows: {len(rows)}"]

    def tally(title: str, counts: Counter, limit: int | None = None) -> None:
        lines.append(f"\n== {title} ==")
        items = counts.most_common() if limit else sorted(counts.items())
        for key, n in items[:limit] if limit else items:
            lines.append(f"  {key or '(empty)':<28} {n}")

    tally("by report type", Counter(r["src_report_type"] for r in rows))
    tally(
        "by index year (district index sections; blank = panel)",
        Counter(r["src_index_year"] for r in rows),
    )
    tally("by src_year (parsed from filename)", Counter(r["src_year"] for r in rows))
    tally("by src_area (parsed from filename)", Counter(r["src_area"] for r in rows), limit=45)

    failed = [r for r in rows if not r["src_date_parsed"]]
    no_area = [r for r in rows if not r["src_area"]]
    lines.append("\n== parse outcomes ==")
    lines.append(f"  date parse failed          {len(failed)} ({len(failed) / len(rows):.1%})")
    lines.append(f"  area/block not in filename {len(no_area)} ({len(no_area) / len(rows):.1%})")
    lines.append(
        f"  redacted/sanitized flagged {sum(r['src_is_redacted'] == 'true' for r in rows)}"
    )
    lines.append(
        f"  url canonicalised          {sum(r['src_url_canonicalised'] == 'true' for r in rows)}"
    )
    lines.append(f"  variant suffix present     {sum(bool(r['src_variant_suffix']) for r in rows)}")
    tally(
        "parse notes",
        Counter(n for r in rows for n in r["src_parse_note"].split(";") if n),
    )
    if unlinked:
        lines.append("\n== index rows with no link at all (not emitted) ==")
        for page, n in unlinked.items():
            lines.append(f"  {page}  {n}")
    if ANOMALIES:
        lines.append("\n== anomalies ==")
        lines.extend(f"  {a}" for a in ANOMALIES)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="re-fetch index pages, ignoring cache")
    ap.add_argument("--report", action="store_true", help="print distributions to stdout")
    ap.add_argument("--out", type=Path, default=MANIFEST_PATH)
    args = ap.parse_args(argv)

    fetcher = Fetcher(refresh=args.refresh)
    rows = build_rows(fetcher)
    write_manifest(rows, args.out)
    print(f"wrote {args.out} ({len(rows)} rows)", file=sys.stderr)
    if args.report:
        unlinked = {
            url: len(district_unlinked_rows(fetcher.get(url)))
            for url in (DISTRICT_URL, DISTRICT_ARCHIVE_URL)
        }
        print(report(rows, unlinked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
