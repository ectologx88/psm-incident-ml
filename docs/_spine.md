# The spine: BSEE "Listing and Status of Incident Investigations"

Working notes for `src/psm/spine.py` → `data/processed/investigations_index.csv`.
All checks below were run 2026-08-02 against live BSEE endpoints.

---

## Headline finding

**The structured export contains NO cause, narrative, findings, or
recommendation data. It is pure incident metadata.** The PDF-parsing pipeline
cannot be skipped or reduced — it is the *only* source of cause text.

The strongest thing the export offers toward causation is `ACCIDENT_TYPE`, and
that is an **incident-classification taxonomy, not a cause**: values are
`- Fire`, `- Pollution`, `- Crane`, `- LTA (>3 days) - Required Evacuation`,
`- Fatality`. Those describe *what happened / what threshold was tripped*
(they mirror the 30 CFR 250.188 reportable-incident categories), not *why*.

### Evidence

Two independent retrieval paths were driven to completion and compared.

| | Path (a) bulk zip | Path (b) ASP.NET postback |
|---|---|---|
| Artifact | `IncInvRawData/mv_acc_investigations.txt` | `IncInv.csv` |
| Rows | 2,014 | 2,014 |
| Columns | 7 | 7 |
| Header | `DATE_OCCURRED, MILITARY_TIME, LEASE_NUMBER, AREA_BLOCK, ACCIDENT_TYPE, PANEL_DISTRICT, STATUS` | `Date Occurred, Military Time, Lease Number, Area/Block, Incident Type, Panel/District, Status` |

Row-multiset comparison of the two: **2,013 of 2,014 rows identical**; the single
difference is an encoding artifact, not data (see Anomaly A1).

A third, independent confirmation: the rendered grid on
`IncidentInvestigations.aspx` declares exactly seven filter editors
(`DXFREditorcol1`…`DXFREditorcol7`) and seven data header cells. There is no
hidden eighth column, no detail-expand row, and **no link column** — the grid
does not point at a report document at all.

Verified: column set is identical across the bulk file, the web CSV export, and
the rendered grid. Did not check the Xls/Xlsx/Pdf/Rtf export buttons — but they
render the same server-side `ASPxGridView`, so a wider column set there is
implausible rather than impossible.

---

## Row count and columns

**2,014 rows.** Not 2,011. The live page states this itself, in the pager:

```
Page 1 of 101 (2014 items)
```

Both retrieval paths independently returned 2,014 data rows. The 2,011 figure in
the task brief is contradicted by the source; the likeliest explanation is drift
(the table is regenerated nightly and three `Pending` investigations were added).

Committed columns — all seven `src_`-prefixed, nothing added, nothing dropped:

| Committed name | Upstream | Notes |
|---|---|---|
| `src_date_occurred` | `DATE_OCCURRED` | `M/D/YYYY`. Range 1995-01-04 → 2026-07-01 |
| `src_military_time` | `MILITARY_TIME` | `H:MM`. 40 rows malformed — Anomaly A5 |
| `src_lease_number` | `LEASE_NUMBER` | `G#####` (1,697) / ` #####` state leases (265) / empty (52) |
| `src_area_block` | `AREA_BLOCK` | e.g. `MC 778`, `HI A379`. 950 distinct |
| `src_accident_type` | `ACCIDENT_TYPE` | **Undocumented upstream** — Anomaly A2. 555 distinct |
| `src_panel_district` | `PANEL_DISTRICT` | `DISTRICT` 1,933 / `PANEL` 81 |
| `src_status` | `STATUS` | `Complete` 2,003 / `Pending` 11 |

---

## Retrieval

**Path (a) worked — no browser, no JavaScript, no session, no postback.**

`RawData.aspx` carries a direct link to a nightly-refreshed zip
(`Incident Investigations | Delimit | 8/2/2026 4:49:02 AM | Updated Daily`):

```bash
curl -L -A "Mozilla/5.0" -e "https://www.data.bsee.gov/Main/RawData.aspx" \
  https://www.data.bsee.gov/Other/Files/IncInvRawData.zip -o data/raw/IncInvRawData.zip
```

| Artifact | SHA256 | Bytes |
|---|---|---|
| `IncInvRawData.zip` | `70cc083f9a20a791889a2bff366894c81f1dde6b8ce958f79434457fa8882faf` | 35,553 |
| `IncInvRawData/mv_acc_investigations.txt` | `8537697daebe6cdb0fef0ffef7f52bc752edc13803df7ed9aa64250074c5a335` | 174,107 |
| `data/processed/investigations_index.csv` | `7aaf19519b2c0ffcaca2981c14f000614e817af49188fa551ab12d01aeaad384` | 147,962 |

Upstream regenerates nightly, so these hashes are a *last-observed fingerprint*,
not a pin. `spine.py` reports drift; it does not fail on it.

Reproduce:

```bash
uv run python -m psm.spine            # cached
uv run python -m psm.spine --force    # re-download
uv run python -m psm.spine --verify   # hashes only
```

Verified idempotent: two consecutive runs produced byte-identical output
(`7aaf1951…` both times).

### Path (b) also works — recorded for cross-validation only

Useful because it is an *independent* code path through BSEE's stack. The export
button is a DevExpress `ASPxButton` with `useSubmitBehavior: false`, so the
button's own `name=` is **not** submitted; the trigger is `__EVENTTARGET`:

```
POST /Other/DataTables/IncidentInvestigations.aspx
  __EVENTTARGET=ASPxFormLayout2$btnCsvExport
  __EVENTARGUMENT=
  __VIEWSTATE / __VIEWSTATEGENERATOR / __EVENTVALIDATION   (scraped from the GET)
  ASPxFormLayout2$ASPxGridView1$DXFREditorcol1..col7=      (empty filter row)
  ASPxFormLayout2$ASPxGridView1$DXSE=
→ 200, Content-Type: text/csv, Content-Disposition: attachment; filename="IncInv.csv"
```

Posting the button as a normal form field (`ASPxFormLayout2$btnCsvExport=CSV`)
with an empty `__EVENTTARGET` returns HTML, not CSV. That was the first attempt
and it failed; `__EVENTTARGET` is the fix.

**Path (c) — browser automation — was never needed.** No reproducibility
problem to report.

---

## Anomalies (logged, not repaired)

Values in `investigations_index.csv` are **verbatim**: no trimming, no case
folding, no date/time repair. `spine.py` emits these as JSONL on stdout.

| ID | Anomaly | n | Notes |
|---|---|---|---|
| A1 | File is **cp1252, not UTF-8** | 1 byte | Byte `0x96` (EN DASH) in an `MC 300` incident type. UTF-8 decode raises; latin-1 silently yields U+0096. The *web CSV export* serves this byte inside a `charset=utf-8` response, so path (b) delivers a mojibake `U+FFFD` there — **the bulk zip is the cleaner source.** |
| A2 | `ACCIDENT_TYPE` is undocumented | — | `FieldDefinitions.aspx?page=incinv` lists **`AREA_BLOCK` twice** (5th row has a blank definition) and never names `ACCIDENT_TYPE`. Positionally the phantom 5th row *is* `ACCIDENT_TYPE`. This confirms and explains the "listed twice" observation in the brief — it is a BSEE documentation defect, not an async-loading truncation. |
| A3 | `LEASE_NUMBER` blank | 52 | Genuinely absent, not a parse failure. |
| A4 | `LEASE_NUMBER` leading whitespace | 265 | State-water leases render as `" 00310"`. Federal leases are `G#####`. Do not `strip()` in place — the padding distinguishes the two regimes. |
| A5 | `MILITARY_TIME` **missing hour** | 40 | Values like `":15"`, `":30"`, `":0"`, and one bare `":"`. Present identically in *both* retrieval paths, so it is upstream, not ours. Almost certainly hour-00 rendering as empty. Field is declared `VARCHAR2(321)` for a `HH:MM` value — the schema is not defending anything. |
| A6 | `ACCIDENT_TYPE` trailing whitespace | 1,589 | e.g. `"- Fire "`. |
| A7 | `ACCIDENT_TYPE` is a delimited multi-value list with a **leading** delimiter | 1,999 | `"- Pollution - Incident >$25K - BLACK OUT– DRIFT OFF- EDS"`. It is `" - "`-joined, but the separator is inconsistent (`"- EDS"` with no leading space) and free text is mixed into the controlled vocabulary. This is why there are 555 "distinct" values for what is a small taxonomy. **Splitting this is a real parsing job, not a `str.split(" - ")`.** |

---

## Join to the district-report PDFs

**There is a join, and it is better than expected — but only because the PDF
index page carries its own metadata table.** The spine itself has no incident ID,
no report number, and no document link.

The district-report listing
(`/what-we-do/incident-investigations/offshore-incident-investigations/district-investigation-reports`,
plus its `/district-investigation-reports-archive` sibling) is a plain HTML
`<table>` whose header is:

```
Date Occurred | Military Time | Lease Number | Area/Block | Accident Type
```

— i.e. **five of the spine's seven columns**, with the PDF hyperlinked on the
date cell. Measured: **1,254 district rows, 1,233 with a PDF link**, spanning
2003-04-11 → 2026-05-24.

### Proposed key

Two tiers, because no single tuple is clean:

1. **`(date, minutes-since-midnight)` + `area/block` as a validator.**
   Time must be normalised to an integer, not string-compared: the spine writes
   `11:38` where the district page writes `1138`, and Anomaly A5 means the hour
   can be missing entirely.
   Area/block must be **prefix-compared after squashing non-alphanumerics** —
   the district page appends a platform designator the spine omits
   (`MU 85 A` vs `MU 85`; `MP 300-B` vs `MP 300`; `HI A 379` vs `HI A379`).
2. **`(date, lease_number)`** as a fallback for rows tier 1 misses.

### Measured match rate

| Outcome | n | % of 1,254 |
|---|---|---|
| Tier 1 unique match | 1,186 | 94.6% |
| Tier 1 **ambiguous** | 0 | 0.0% |
| Tier 1 area/block conflict | 15 | 1.2% |
| Tier 2 (`date`+`lease`) rescue | 10 | 0.8% |
| **Total unique** | **1,196** | **95.4%** |
| Unresolved | 58 | 4.6% |

**Zero ambiguous matches** is the important number — when the key hits, it hits
exactly one spine row. Naive string equality on the same fields scores 36%, so
the normalisation is doing nearly all the work; do not skip it.

Residual failures are source dirt, e.g. one district row records area/block as
`El 307A` — lowercase L for Eugene Island's `EI`.

### The number that constrains the project

Matching runs ~95% *in the PDF→spine direction*. The reverse is far worse:
**roughly 818 of 2,014 spine rows (~41%) have no district PDF at all.** Causes:
the district listing starts in 2003 while the spine reaches back to 1995; 81
rows are `PANEL` investigations published on a separate page; and 11 are
`Pending`. Plan for a spine where **cause text is available for well under
two-thirds of rows**, and make `src_cause_status` carry that absence honestly
rather than dropping the rows.

Not built — assessment only, per scope. Panel-report joinability was **not**
measured.

---

## Deviations from repo convention

`spine.py` prints anomaly JSONL to stdout instead of appending to
`data/interim/anomalies.jsonl`, to avoid contending with the concurrently-written
harvest pipeline for that file. Wire it up with a redirect, or fold the
`find_anomalies()` call into whichever module ends up owning that file.
