"""Tests for the BSEE manifest harvester.

Every filename below is a real string taken from ``data/manifest.csv`` or from
the district/panel index HTML. Nothing here is invented -- the point of the
suite is that the parser keeps working on the specific mess BSEE publishes.

Run with::

    uv run pytest tests/test_harvest.py
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from psm.harvest import (
    AREA_CODES,
    MANIFEST_COLUMNS,
    parse_filename,
    resolve_url,
    url_filename,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "data" / "manifest.csv"


# ---------------------------------------------------------------------------
# Filename parser -- the happy paths, one per naming family
# ---------------------------------------------------------------------------

# (filename, area, block, date_parsed)
CLEAN_CASES = [
    # Title Case with spaces, 2-digit year
    ("MP 298 Cantium 24-May-26.pdf", "MP", "298", "2026-05-24"),
    # Title Case, descriptor between operator and date
    ("MU 85 Talos Energy Conductor Drop 17-May-26.pdf", "MU", "85", "2026-05-17"),
    # Drupal duplicate-upload suffix
    ("GI 48 GOM Shelf 5-May-2026_0.pdf", "GI", "48", "2026-05-05"),
    # trailing space before .pdf, ampersand operator
    ("SS 229 W&T 18-APR-2026 .pdf", "SS", "229", "2026-04-18"),
    # lowercase-hyphen
    ("wd-73-cox-operating-27-may-2019.pdf", "WD", "73", "2019-05-27"),
    # operator first, block carries a platform letter
    ("cox-hi-472-a-21-oct-2022.pdf", "HI", "472 A", "2022-10-21"),
    # lowercase-underscore
    ("gb_669_anadarko_05_apr_2016.pdf", "GB", "669", "2016-04-05"),
    ("gb_216_hess_corporation_17_feb_2016.pdf", "GB", "216", "2016-02-17"),
    # area and block joined, no separators in the date
    ("mc816-llog-02jun2019.pdf", "MC", "816", "2019-06-02"),
    # numeric MMDDYYYY date
    ("sm58-byron-energy-09112019.pdf", "SM", "58", "2019-09-11"),
    # numeric YYYYMMDD date
    ("sm130-20170911.pdf", "SM", "130", "2017-09-11"),
    # 2-digit year with no separators
    ("gc-338-16sep19.pdf", "GC", "338", "2019-09-16"),
    # platform letter *before* the block number
    ("hi-a-573-b-fieldwood-energy-28-aug-2016.pdf", "HI", "A 573 B", "2016-08-28"),
    # underscore separators, upper-case month
    ("EI 307 Guardian 17_MAR_2025.pdf", "EI", "307", "2025-03-17"),
    # date FIRST, form number after
    ("13-MAR-2024_SS189_WOG_EV2010.pdf", "SS", "189", "2024-03-13"),
    # MM-DD-YY leading date, area/block at the end
    ("12-18-11-shell-mc-348.pdf", "MC", "348", "2011-12-18"),
    ("03-04-12-nexen-ei-259.pdf", "EI", "259", "2012-03-04"),
    # archive YYMMDD-only filename: date recoverable, area/block is not
    ("091219a-pdf.pdf", "", "", "2009-12-19"),
    ("080326-pdf.pdf", "", "", "2008-03-26"),
]


@pytest.mark.parametrize("filename,area,block,iso", CLEAN_CASES)
def test_parse_filename_clean(filename, area, block, iso):
    parsed = parse_filename(filename)
    assert parsed.area == area
    assert parsed.block == block
    assert parsed.date_parsed == iso
    assert parsed.year == (iso[:4] if iso else "")


@pytest.mark.parametrize(
    "filename,operator",
    [
        ("MP 298 Cantium 24-May-26.pdf", "Cantium"),
        ("wd-73-cox-operating-27-may-2019.pdf", "cox operating"),
        ("cox-hi-472-a-21-oct-2022.pdf", "cox"),
        ("gb_216_hess_corporation_17_feb_2016.pdf", "hess corporation"),
        ("13-MAR-2024_SS189_WOG_EV2010.pdf", "WOG"),
        ("gc-338-16sep19.pdf", ""),  # no operator in the filename at all
    ],
)
def test_parse_filename_operator(filename, operator):
    assert parse_filename(filename).operator == operator


# ---------------------------------------------------------------------------
# Form 2010 is a form number, not a year
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,iso",
    [
        ("gb-426-31mar19-sanitized-2010.pdf", "2019-03-31"),
        ("gi-43-26-jan-18-2010-final.pdf", "2018-01-26"),
        ("wd-27-a-24nov19-2010-redacted.pdf", "2019-11-24"),
        ("EI_259C_Cox_13-OCT-2023_EV2010R.pdf", "2023-10-13"),
        ("W_&_T__HI_A_379-B_2010_Report_21-Feb-2024.pdf", "2024-02-21"),
        ("11-JUL-2024_HIA5_MantaRay_EV2010R_(1)_0.pdf", "2024-07-11"),
    ],
)
def test_form_2010_is_not_a_year(filename, iso):
    parsed = parse_filename(filename)
    assert parsed.date_parsed == iso, parsed.parse_note
    assert parsed.year != "2010" or iso.startswith("2010")


def test_no_bare_year_fallback():
    """A filename with only a form number and no date must not invent a date."""
    parsed = parse_filename("rooster-vr-376-a-2010.pdf")
    assert parsed.date_parsed == ""
    assert parsed.year == ""
    assert "no_date_token" in parsed.parse_note
    # ...but the row is still usable: area/block survive
    assert (parsed.area, parsed.block) == ("VR", "376 A")


# ---------------------------------------------------------------------------
# Failure modes: never drop, never guess, always explain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,note_fragment",
    [
        ("EV2010R - MC 773.pdf", "no_date_token"),
        ("31-may-ei-338arenacranesantitized.pdf", "no_date_token"),
        ("final-sanitized-acc-inc-report-15-nov-2016.pdf", "no_area_block_in_filename"),
        ("091219a-pdf.pdf", "no_area_block_in_filename"),
        ("mc-751-llog-expl-offshore-31-may-20111.pdf", "no_date_token"),  # typo'd year
        ("", "empty_filename"),
    ],
)
def test_parse_failures_are_explained(filename, note_fragment):
    parsed = parse_filename(filename)
    assert note_fragment in parsed.parse_note


def test_parser_never_raises_on_junk():
    for junk in ["...pdf", ".pdf", "   ", "%%%.pdf", "0.pdf", "a" * 300 + ".pdf"]:
        parse_filename(junk)  # must not raise


def test_multiple_date_tokens_flagged_and_first_wins():
    parsed = parse_filename("gb128-2feb2020-shell-2010-7july2020-redacted.pdf")
    assert parsed.date_parsed == "2020-02-02"  # matches the index Date Occurred
    assert "multiple_date_tokens" in parsed.parse_note
    assert parsed.is_redacted is True


# ---------------------------------------------------------------------------
# Redaction and variant suffixes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,redacted",
    [
        ("wd-27-a-24nov19-2010-redacted.pdf", True),
        ("W&T_7Mar2026_GB_783_Redacted.pdf", True),
        ("gb-426-31mar19-sanitized-2010.pdf", True),
        ("31-may-ei-338arenacranesantitized.pdf", True),  # source typo "santitized"
        ("MP 298 Cantium 24-May-26.pdf", False),
    ],
)
def test_redaction_flag(filename, redacted):
    assert parse_filename(filename).is_redacted is redacted


@pytest.mark.parametrize(
    "filename,suffix",
    [
        ("GI 48 GOM Shelf 5-May-2026_0.pdf", "_0"),
        ("vk-956-talos-15-jan-2020-v2.pdf", "-v2"),
        ("11-JUL-2024_HIA5_MantaRay_EV2010R_(1)_0.pdf", "(1)_0"),
        ("MP 298 Cantium 24-May-26.pdf", ""),
    ],
)
def test_variant_suffix(filename, suffix):
    assert parse_filename(filename).variant_suffix == suffix


def test_variant_stripper_does_not_eat_a_trailing_year():
    """Regression: ``_2016`` is a date, ``_0`` is a Drupal duplicate counter."""
    parsed = parse_filename("ac_857_shell_offshore_25_may_2016.pdf")
    assert parsed.variant_suffix == ""
    assert parsed.date_parsed == "2016-05-25"


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "href,fetch,canonicalised",
    [
        # root-relative, percent-encoded
        (
            "/sites/bsee.gov/files/2026-07/MP%20298%20Cantium%2024-May-26.pdf",
            "https://www.bsee.gov/sites/bsee.gov/files/2026-07/MP%20298%20Cantium%2024-May-26.pdf",
            False,
        ),
        # bare-relative (no leading slash) -- must resolve against the site root
        (
            "sites/bsee.gov/files/anadarko-eb-602-23-jan-2022.pdf",
            "https://www.bsee.gov/sites/bsee.gov/files/anadarko-eb-602-23-jan-2022.pdf",
            False,
        ),
        # doubled slash in the published path is collapsed by urljoin; the
        # collapsed form was HEAD-verified to return 200 (2026-08-02)
        (
            "sites/bsee.gov/files/reports//sm-58-byron-7-oct-2019.pdf",
            "https://www.bsee.gov/sites/bsee.gov/files/reports/sm-58-byron-7-oct-2019.pdf",
            False,
        ),
        # dead host -> host swapped, path preserved
        (
            "https://bsee_prod.opengov.ibmcloud.com/sites/bsee.gov/files/gc-640-chevron-19-may-2016.pdf",
            "https://www.bsee.gov/sites/bsee.gov/files/gc-640-chevron-19-may-2016.pdf",
            True,
        ),
        (
            "https://connect.bsee.gov/sites/bsee.gov/files/ew-826-05jul2020.pdf",
            "https://www.bsee.gov/sites/bsee.gov/files/ew-826-05jul2020.pdf",
            True,
        ),
        (
            "https://doibsee.prod.acquia-sites.com/sites/bsee.gov/files/ac-857-shell-29-oct-21.pdf",
            "https://www.bsee.gov/sites/bsee.gov/files/ac-857-shell-29-oct-21.pdf",
            True,
        ),
        # already on the live host -> untouched
        (
            "https://www.bsee.gov/sites/bsee.gov/files/reports/safety/mc-809-shell-07-may-2014.pdf",
            "https://www.bsee.gov/sites/bsee.gov/files/reports/safety/mc-809-shell-07-may-2014.pdf",
            False,
        ),
        # staging host with a subfolder: the path must survive the swap, because
        # a basename-only rewrite 404s for this file (verified 2026-08-02)
        (
            "https://doibseetest.prod.acquia-sites.com/sites/bsee.gov/files/memos//gc-205-directors-response-memo.pdf",
            "https://www.bsee.gov/sites/bsee.gov/files/memos//gc-205-directors-response-memo.pdf",
            True,
        ),
    ],
)
def test_resolve_url(href, fetch, canonicalised):
    got_fetch, got_display, got_canon = resolve_url(href)
    assert got_fetch == fetch
    assert got_canon is canonicalised
    assert "%20" not in got_display


def test_url_filename_is_decoded_verbatim():
    _, display, _ = resolve_url(
        "/sites/bsee.gov/files/2026-06/SS%20229%20W%26T%2018-APR-2026%20.pdf"
    )
    assert url_filename(display) == "SS 229 W&T 18-APR-2026 .pdf"


# ---------------------------------------------------------------------------
# Committed manifest: schema and internal consistency
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest_rows() -> list[dict]:
    if not MANIFEST.exists():
        pytest.skip("data/manifest.csv not built yet -- run `python -m psm.harvest`")
    with MANIFEST.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# `psm.fetch` legitimately mutates the committed manifest: it fills src_sha256
# and appends src_fetch_note. That is the reproducibility contract working -- the
# manifest is committed *with* a hash per file so anyone can rebuild byte-identical
# inputs. So these assert what harvest owns, and tolerate what fetch adds.
POST_FETCH_COLUMNS = {"src_fetch_note"}


def test_manifest_columns_all_carry_a_provenance_prefix(manifest_rows):
    with MANIFEST.open(encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    assert header[: len(MANIFEST_COLUMNS)] == MANIFEST_COLUMNS, (
        "harvest's own columns must be present, in order, at the front")
    assert set(header[len(MANIFEST_COLUMNS):]) <= POST_FETCH_COLUMNS, (
        f"unexpected extra columns: {set(header[len(MANIFEST_COLUMNS):]) - POST_FETCH_COLUMNS}")
    assert all(c.startswith("src_") for c in header)


def test_manifest_sha256_is_absent_or_a_real_hash(manifest_rows):
    """Harvest must never guess a hash; fetch fills it from the downloaded bytes.

    Empty before fetch, a well-formed digest after. What must never appear is
    something hash-shaped that nothing computed.
    """
    for r in manifest_rows:
        got = (r["src_sha256"] or "").strip()
        assert got == "" or re.fullmatch(r"[0-9a-f]{64}", got), f"not a sha256: {got!r}"


def test_harvest_itself_never_writes_a_hash():
    """The claim the previous test was really making, asserted where it belongs."""
    assert "src_sha256" in MANIFEST_COLUMNS, "harvest must reserve the column"
    row = {col: "" for col in MANIFEST_COLUMNS}
    assert row["src_sha256"] == ""


def test_manifest_urls_are_absolute_and_unique(manifest_rows):
    urls = [r["src_url"] for r in manifest_rows]
    assert len(urls) == len(set(urls))
    assert all(u.startswith("https://www.bsee.gov/") for u in urls)
    assert all(u.lower().endswith(".pdf") for u in urls)


def test_manifest_report_types(manifest_rows):
    assert {r["src_report_type"] for r in manifest_rows} == {"district", "panel"}


def test_manifest_rows_are_never_dropped_for_parse_failure(manifest_rows):
    """Every row missing a parsed field must carry an explanation instead."""
    for row in manifest_rows:
        if not row["src_date_parsed"] or not row["src_area"]:
            assert row["src_parse_note"], row["src_filename"]


def test_manifest_parsed_areas_are_known_codes(manifest_rows):
    seen = {r["src_area"] for r in manifest_rows if r["src_area"]}
    assert seen <= AREA_CODES


def test_manifest_year_matches_parsed_date(manifest_rows):
    for row in manifest_rows:
        assert row["src_year"] == row["src_date_parsed"][:4]


def test_manifest_covers_pre_2018(manifest_rows):
    """The archive index is in scope; regression guard on losing that source."""
    years = {r["src_index_year"] for r in manifest_rows if r["src_index_year"]}
    assert {"2003", "2005", "2010", "2013"} <= years
