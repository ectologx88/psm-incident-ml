# Harvest findings — BSEE incident investigation report URL manifest

Working notes behind `src/psm/harvest.py` and `data/manifest.csv`.
All counts below were produced in one session on **2026-08-02** against pages
fetched that day. Anything not verified in that session is flagged as such.

Rebuild:

```bash
uv run python -m psm.harvest --report      # uses the cached index HTML
uv run python -m psm.harvest --refresh     # re-fetches the index pages
```

Re-running with the same cached index HTML produces a **byte-identical**
`data/manifest.csv` (verified: `diff -q` on two consecutive runs).

---

## 1. The true count, and how investigation reports were distinguished

**1,302 investigation-report PDFs** — 1,241 district, 61 panel.

The distinguishing rule is *structural*, not a URL-pattern heuristic, because the
files are scattered across at least 20 different Drupal upload folders
(`/files/`, `/files/2026-07/`, `/files/reports/safety/`,
`/files/incident-summaries/inspection-and-enforcement/`,
`/files/incident-statisticssummaries-fatalities/forms/`, …). Folder is
meaningless; position on the index page is not.

| Source | Rule |
|---|---|
| district | the `<a href>` must sit in a **data row of a year table** inside `<main>` on a district index page. Every year table has the header `Date Occurred \| Military Time \| Lease Number \| Area/Block \| Accident Type`, and the report link is in cell 0. |
| panel | the `<a href>` must be an attachment on a `/panel-investigation/…` detail page that is itself linked from the paginated panel listing table. |

Where the count comes from:

| Index page | Data rows | PDF `<a>` occurrences | Unique hrefs | Notes |
|---|---|---|---|---|
| `district-investigation-reports` (2014–2026) | 592 | 581 | 576 | 15 rows link a Drupal node alias instead of a PDF; following one hop yields 15 more files. 0 rows with no link at all. |
| `…/district-investigation-reports-archive` (2003–2013) | 662 | 656 | 650 | 6 rows carry no link at all — listed incidents with no published report. |
| panel listing (`?page=0..2`) | 36 entries | — | 61 | 35 detail pages contribute; 1–4 attachments each. |

576 + 15 + 650 = **1,241 district**. The two district pages share **zero**
filenames (checked by decoded basename), so nothing is double-counted.
61 panel files bring the manifest to **1,302 rows**.

A page-wide `grep 'href=.*\.pdf'` on the current district page happens to give
the same 576, because that page contains **no** non-investigation PDFs — no nav
PDFs, no forms. That is luck, not a definition, and it does not hold for the
panel side (see §5).

### Not the same thing as "number of BSEE investigations"

BSEE's Data Center grid *Listing and Status of Incident Investigations*
(`https://www.data.bsee.gov/Other/DataTables/IncidentInvestigations.aspx`)
reports **2,014 items** with a `Status` column of `Complete` / `Pending`. That
grid carries **no PDF links at all** (verified: 0 `.pdf` hrefs on page 1) — it is
an investigation *register*, not a report index. 1,302 published PDFs against
2,014 registered investigations is not a contradiction.

---

## 2. The 576-vs-342 discrepancy

**576 is correct** for unique PDF hrefs on the current district index page, and
581 for link occurrences. The 5-link gap comes from exactly **two** hrefs:
`gb_216_hess_corporation_17_feb_2016.pdf` (linked from 5 rows) and
`mc-809-shell-07-may-2014.pdf` (2 rows).

**342 could not be reproduced.** Every subsetting rule tried on the page as it
stands today missed:

| Subset of the current district page | Unique PDFs |
|---|---|
| all years (2014–2026) | 576 |
| 2018–2026 (the range the prior count claimed) | **362** |
| 2018–2025 | 346 |
| 2014–2020 | 349 |
| 2019–2026 | 323 |
| after stripping `_0` / `-v2` / `-redacted` variants | 576 (no collisions) |
| unique decoded basenames | 576 |

The prior count was wrong on **both** figures it asserted:

* **Range.** The page is not 2018–2026. It has `<h2>` year sections for
  **2014 through 2026**, thirteen `<table>` elements, all present in the plain
  `curl` HTML with no JavaScript.
* **Count.** The closest reproducible number to 342 is 362 (2018–2026 unique
  links), 20 higher. Nothing produced 342.

Most likely explanation — stated as a hypothesis, **not verified**: 342 was a
count of visible rows in a browser over a subset of years, taken before the page
grew. It is not recoverable from the current HTML by any rule tested.

What the naive grep *does* over-count relative to distinct *reports* is small and
explainable: the 5 duplicate link occurrences above, and 22 files across the
whole manifest carrying Drupal duplicate-upload or revision suffixes
(`_0` ×11, `-v2` ×7, `(1)` ×2, `(1)_0`, `-v4`). Those are genuinely distinct
files at distinct URLs and are kept, with `src_variant_suffix` set.

---

## 3. Pre-2018 — where the older reports live

**They were on the district index page the whole time, plus a linked archive
page.** There is no gap to hunt.

* The current district page carries year sections **2014–2026** (not 2018–2026).
* An easily-missed **`View Archive`** link near the top of that page
  (`/what-we-do/incident-investigations/offshore-incident-investigations/district-investigation-reports/district-investigation-reports-archive`)
  leads to a single 205 KB table covering **2003–2013**, with in-page anchors
  `#2013 … #2003`. It holds 650 unique report PDFs.

District coverage by index-page year section, as harvested:

```
2003   3     2009  78     2015  69     2021  59
2004  16     2010  38     2016  46     2022  41
2005  58     2011  40     2017  46     2023  39
2006  88     2012  83     2018  39     2024  33
2007  96     2013  62     2019  50     2025  39
2008  88     2014  68     2020  46     2026  16
```

### The "since 2005-01-01" claim

That claim is **not on the district index page**. It comes from the Data Center
page, verbatim:

> "Panel reports issued since 1992 are available from this website. District
> Investigation Reports issued since January 1, 2005 are available from this
> website."
> — `data.bsee.gov/Other/DataTables/IncidentInvestigations.aspx`, fetched 2026-08-02

The district archive **exceeds** that claim: it publishes 3 reports dated 2003
and 16 dated 2004. So the floor is 2003, not 2005.

### The panel side is a clean negative

The same Data Center note claims panel reports **since 1992**. The published
panel listing does not support that:

* The listing is a 3-page Drupal view with **36 entries**, document numbers
  `2008-049` (oldest) through `2024-01` (newest). Nothing pre-2008.
* The panel page has **no** archive link — unlike the district page, which does.
* `https://www.bsee.gov/sitemap.xml` → **404**, so the site cannot be enumerated
  that way.
* `https://www.bsee.gov/panel-investigation` (the parent path) → **404**.
* BSEE's own site search (`/search?keys=…`) returns "No results found" for every
  query tried — it appears non-functional, so it could not be used to confirm
  or refute.

**Conclusion:** panel investigation reports from 1992–2007 are *not discoverable*
through any BSEE index reachable from the panel page. Whether they exist
elsewhere (FOIA library, MMS-era archive) was **not checked**.

---

## 4. Distributions and parse quality

Full output: `uv run python -m psm.harvest --report`.

**By report type:** district 1,241 · panel 61.

**By `src_year` (parsed from the filename; blank = no date token in the filename):**

```
(blank)  58    2008  88    2014  71    2020  47    2026  16
2003      3    2009  77    2015  70    2021  59
2004     16    2010  38    2016  48    2022  41
2005     58    2011  39    2017  46    2023  40
2006     88    2012  80    2018  40    2024  33
2007     97    2013  64    2019  49    2025  36
```

Note this is the **filename** year and will not always equal the incident year —
see the cross-check below.

**By `src_area` (parsed from the filename), top of the distribution:**

```
(blank) 571   MP 33   WD 28   KC 19   GI 13   MU  7   MO 3
MC 110        HI 32   VR 28   VK 17   EC 12   PL  6   BA 2
GC  90        SM 32   EB 27   SP 17   EW 12   DC  4   PN 2
EI  49        SS 32   ST 27   WC 15           MI  4
GB  44        WR 32   AC 28
```

plus one each of GA, HIA, AS, BM, BS, SE.

**Parse outcomes (n = 1,302):**

| Outcome | Count | Rate |
|---|---|---|
| date parse failed (`src_date_parsed` empty) | **58** | **4.5 %** |
| area/block not recoverable from the filename | 571 | 43.9 % |
| redaction flagged from the filename | 29 | 2.2 % |
| URL canonicalised (dead host) | 25 | 1.9 % |
| variant suffix present (`_0`, `-v2`, `(1)_0`) | 22 | 1.7 % |

The 43.9 % area/block miss is dominated by the archive era: 470 files are named
only `YYMMDD[a]-pdf.pdf` (`091219a-pdf.pdf`, `080326-pdf.pdf`) with no area,
block or operator in the name at all.

### The area/block caveat that matters

**Filename-derived `src_area` / `src_block` are a convenience, not a source of
truth.** The authoritative area/block is **Form 2010 field 4 inside the PDF**.
Filenames omit it entirely for 44 % of rows, and where both exist they sometimes
disagree with the index table (e.g. `ac-857-shell-13-jun-2014.pdf` sits in a row
whose `Area/Block` cell reads `VR 279`). The index table's verbatim cell is
carried as `src_index_area_block` precisely so this can be checked rather than
assumed.

### Falsifiable check: filename date vs. the index table's own date

Across district rows with both a parsed filename date and a parsable
`Date Occurred` cell:

```
match 1,203   differ 27   no filename date 10   unparsable index date 1
```

**97.8 % exact agreement.** The 27 disagreements are source inconsistencies, not
parser failures — e.g. `07-feb-2007-p00441.pdf` is filed under the archive's
**2009** section; `gc-338a-murphy-…-15-july-2013.pdf` sits in a row dated
2012-09-29. Logged, not repaired.

A separate check validates the archive `YYMMDD` filename convention: of 463
files whose whole name is `YYMMDD[a]-pdf.pdf`, **462 decode to exactly the
`Date Occurred` value** in their own row. The one exception,
`061204-pdf.pdf` in a row dated `12-05-2006`, is off by one day and is left
as-is.

---

## 5. Anomalies (logged, not repaired)

**Dead hosts in published hrefs — 25 rows (1.9 %).** Four non-live hosts appear:
`bsee_prod.opengov.ibmcloud.com` (an underscore is illegal in a DNS label, so it
cannot resolve at all), `connect.bsee.gov`, `doibsee.prod.acquia-sites.com` and
`doibseetest.prod.acquia-sites.com` — the last two are leaked Acquia staging
hosts. The fix is a **host swap with the path preserved**. Verified by HEAD
request on 2026-08-02: all 25 as-published URLs fail, all 25 host-swapped URLs
return 200. A basename-only rewrite is *not* sufficient — it 404s for the
`memos/` and `safety-alerts/` subfolders on the panel side (checked on 3 files).
The original href is kept verbatim in `src_url_published` and the rewrite is
flagged in `src_url_canonicalised`; nothing is silently repaired.

**Link liveness spot-check.** 40 randomly sampled non-canonicalised rows (seed 7)
all returned HTTP 200. One known dead link found incidentally and **not** in the
sample: `…/files/reports/safety/st-285-w-t-offshore-inc-20-dec-2013.pdf` returns
404 both as published and under a flat rewrite. Liveness for the full 1,302 was
**not** checked — that belongs to `psm.fetch`.

**One PDF, several index rows — 10 files.** BSEE occasionally links the same
report from two incident rows. The worst case,
`gb_216_hess_corporation_17_feb_2016.pdf`, is linked from **5** rows.
`12-18-11-shell-mc-348.pdf` is linked from both a `KC/736` row and an `MC/348`
row on the same date. The manifest is keyed on the file, so the *first* row's
metadata is carried and the collision is counted in `src_index_row_count`
(> 1 means the other rows' metadata is not in this manifest).

**Index rows with no report at all — 6**, all on the archive page (2005–2010),
e.g. `10-22-2010 · P00205 · LA/6912 · Pollution`. Listed incidents, no published
PDF. They are reported by `--report` and deliberately **not** emitted as rows.

**Panel detail pages carry supporting attachments.** Only 20 of 35 panel detail
pages have a single attachment; the rest have 2–4, mixing the panel report with
director response memos, safety alerts and multi-part appendices
(`bsee-director-respons-memo-st-220.pdf`,
`sems-accident-investigation-report-walter-report-part-1.pdf`,
`bsee-safety-alert-389.pdf`). **`src_attachment_index = 0` is document order,
not "the report"** — for panel `2017-002` the first attachment is
`acting-director-schneider-memo-on-panel-report.pdf`. Filter downstream; do not
assume index 0 is the investigation report.

**Duplicate panel node.** Panel `2010-025` appears twice in the listing (Drupal
node and a `-0` duplicate). Both point at the same PDF, so it dedupes to one row.

**Stale label.** The archive page's back-link reads "2021 - 2014" while the page
it returns to now covers 2014–2026.

**Source-data typos preserved.** `El 307A` (capital-E lowercase-L for `EI`) in an
index Area/Block cell; `mc-751-llog-expl-offshore-31-may-20111.pdf` (five-digit
year — parses to no date and carries `no_date_token`);
`santitized`/`santized` misspellings of "sanitized" (matched by the redaction
regex on purpose); `direcor-letter-…pdf`. None corrected.

---

## 6. Filename parsing rules worth knowing

**`2010` in a BSEE filename is almost always the MMS Form 2010 number, not a
year** — it leaks in as `EV2010`, `EV2010R`, `2010_Report`, or a trailing
`-2010`. Consequently the parser **never falls back to a bare 4-digit year**. A
date is accepted only from an explicit date *token*; otherwise the row is emitted
with an empty date and `src_parse_note = no_date_token`.

Date token families handled (all tested in `tests/test_harvest.py` against real
filenames):

| Shape | Example |
|---|---|
| day–monthname–year, 2 or 4-digit year | `24-May-26`, `05_may_2016`, `31mar19`, `7july2020`, `17_MAR_2025` |
| monthname first | `may-24-2026` |
| `YYYYMMDD` | `sm130-20170911.pdf` |
| `MMDDYYYY` | `sm58-byron-energy-09112019.pdf` |
| `MM-DD-YYYY` | `12-20-2013` |
| `MM-DD-YY` | `12-18-11-shell-mc-348.pdf` |
| whole-name `YYMMDD[a]` (archive era) | `091219a-pdf.pdf` |

Two-digit years expand to `20xx` (every BSEE report in scope post-dates 2000).
`MM-DD-YY` is read US month-first, matching the index tables' own
`MM-DD-YYYY` column; both halves are range-checked.

Four filenames contain **two** date tokens (`gb128-2feb2020-shell-2010-7july2020-redacted.pdf`
— incident date and publication date). The parser takes the **first** and sets
`multiple_date_tokens:N`. Checked against the index `Date Occurred` cell: the
first token is the incident date in all 4 cases.

Area/block uses an area-abbreviation vocabulary derived empirically from the
`Area/Block` column of every year table on both district pages, and handles
three layouts: `MP 298`, `sm58` (joined), and `hi-a-573-b` (platform letter
before the block number). Operator is whatever survives after removing the
area/block run, the date token, and a small explicit noise list
(`ev2010r`, `report`, `final`, `redacted`, …).

---

## 7. Manifest schema notes

* `src_url` — absolute, percent-encoded, request-ready.
  `src_url_display` — same URL decoded (`SS 229 W&T 18-APR-2026 .pdf`).
  `src_url_published` — the href exactly as BSEE published it, including
  bare-relative forms with no leading slash and doubled slashes.
* `src_sha256` is present and **empty by design**. `psm.fetch` fills it after
  download; harvest downloads nothing.
* `src_index_*` columns are verbatim from the index table row.
  `src_area` / `src_block` / `src_operator` / `src_date_*` are parsed from the
  **filename** and may disagree with them — that is the point.
* Bare-relative hrefs are resolved against `https://www.bsee.gov/`, never against
  an index-page URL with a path (`urljoin` would mangle them).
* Index HTML is cached under `data/interim/harvest_cache/` (gitignored), so
  re-runs are network-free and reproducible. `--refresh` re-fetches.
  Requests are rate-limited to one per 1.5 s with a descriptive User-Agent.

## 8. Not checked

* Liveness of all 1,302 URLs — only 65 were HEAD-checked (25 canonicalised + a
  40-row random sample).
* Whether any PDF is a scan-only image, or actually a Form 2010 at all.
* Whether the 6 unlinked archive rows have reports available elsewhere.
* Whether pre-2008 panel reports exist outside bsee.gov's panel listing.
* Paginating the Data Center grid (101 pages, DevExpress postbacks, and it
  carries no PDF links).
