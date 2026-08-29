# Findings

Running verification log. Dated, append-only. Records what was checked, by what
method, and what came back — including negative results and things that
contradicted our starting assumptions.

---

## 2026-08-02 — Stage 1: acquisition and vocabulary induction

### Summary of what changed relative to the project brief

| Brief said | Actually |
|---|---|
| 2,011 investigations in the structured listing | **2,014** (the site's own pager says `Page 1 of 101 (2014 items)`) |
| 342 PDF links, covering 2018–2026 | **576 unique PDF hrefs**, covering **2014–2026** on the same page |
| Cause vocabulary has 6 categories incl. "Human error" | 6 categories confirmed, but the label is **"Human Performance Error"** |
| Typing standardises around 2023–24 | Boundary is **2021→2022**, and it is a **gradient, not a switch** |
| Typing may be district-specific | **It is not.** Temporal signal is ~3x stronger than district |
| Structured export might carry cause data | **It does not.** Metadata only — the PDF pipeline is required |

---

### Task 2 — does the structured export carry cause data?

**No. Definitively metadata only.** This was the gating question, and the answer
means the PDF pipeline cannot be reduced.

Seven columns: `DATE_OCCURRED`, `MILITARY_TIME`, `LEASE_NUMBER`, `AREA_BLOCK`,
`ACCIDENT_TYPE`, `PANEL_DISTRICT`, `STATUS`. No cause, narrative, findings, or
recommendation field.

Verified three independent ways rather than by inference:
1. Bulk zip export → 7 columns.
2. ASP.NET CSV export driven to completion → same 7 columns.
3. The rendered grid declares exactly 7 filter editors (`DXFREditorcol1`…`col7`)
   and 7 header cells — no hidden column, no detail row, **no link column**.

Row-multiset diff of paths 1 and 2: 2,013 of 2,014 rows identical; the single
difference is an encoding artifact, not data.

`ACCIDENT_TYPE` is the closest thing to causation and is **not** a cause. It is
an incident *classification* (`- Fire`, `- Pollution`, `- Crane`, `- Fatality`)
mirroring the 30 CFR 250.188 reportable-incident thresholds — *what tripped*,
not *why*.

**Retrieval — no browser, no postback, no session required:**

```bash
curl -L -A "Mozilla/5.0" -e "https://www.data.bsee.gov/Main/RawData.aspx" \
  https://www.data.bsee.gov/Other/Files/IncInvRawData.zip -o data/raw/IncInvRawData.zip
```

Verified idempotent across two consecutive runs (byte-identical output).

**Gotchas recorded so nobody re-derives them:**
- The file is **cp1252, not UTF-8** (one `0x96` EN DASH). UTF-8 decode raises;
  latin-1 silently corrupts. The *web CSV export* serves that byte inside a
  `charset=utf-8` response, so the postback path yields mojibake — **the bulk
  zip is the cleaner source**, the opposite of the intuitive assumption.
- The CSV export button sets `useSubmitBehavior: false`, so its `name=` is never
  submitted. Posting `ASPxFormLayout2$btnCsvExport=CSV` returns HTML; the actual
  trigger is `__EVENTTARGET=ASPxFormLayout2$btnCsvExport`.
- The field-definitions page lists `AREA_BLOCK` twice and never names
  `ACCIDENT_TYPE`. This is a **BSEE documentation defect**, not async
  truncation: the phantom row with a blank definition is positionally
  `ACCIDENT_TYPE`. The real column set is 7 and the page does list 7 rows,
  just mislabelled.

**Anomalies logged, not repaired:** 40 rows with a missing hour in
`MILITARY_TIME` (`":15"`, `":0"`, one bare `":"`) — present in *both* retrieval
paths, therefore upstream; 52 blank lease numbers; 265 leases with meaningful
**leading whitespace** (state vs federal — do not `strip()`).

**Join to the district PDFs — viable, but the reverse direction is the problem.**
Key is `(date, minutes-since-midnight)` with area/block as validator, falling
back to `(date, lease_number)`.

| Outcome | n | % |
|---|---|---|
| Tier 1 unique | 1,186 | 94.6% |
| Ambiguous | 0 | 0.0% |
| Tier 2 rescue | 10 | 0.8% |
| **Total unique** | **1,196** | **95.4%** |

Both normalisations are load-bearing — naive string equality on the same fields
scores 36%. **The number that should shape planning:** roughly **818 of 2,014
spine rows (~41%) have no district PDF at all** (the listing starts 2003, the
spine reaches 1995, plus 81 `PANEL` rows and 11 `Pending`). Budget for cause
text on well under two-thirds of rows.

---

### Extraction — text-stream order vs visual order

**Confirmed on real files.** `page.extract_text()` on a 2026 report returns:

```
1. OCCURRED
STRUCTURAL DAMAGE
DATE: 24-MAY-2026 TIME: 1138 HOURS CRANE
```

— two columns interleaved, checkbox `X` marks detached from their labels.

**The fix is cheaper than expected.** Bucketing words into rows by `top`
(tolerance 2.5pt), sorting rows top-to-bottom and words left-to-right, and
splitting the form face at its gutter, fully restores reading order. Field
labels then land *before* their content, so the reported label-after-content
inversion is purely an artifact of stream-order extraction, not a property of
the documents. No OCR needed anywhere in the sample — all 63 files had a text
layer.

Three bugs found and fixed while building this, worth recording because each
produced *plausible but wrong* output rather than an error:

1. **Gutter detection always returned `None`.** The row-crossing test correctly
   identified x≈270–302 as clear, then a second widening step re-measured the
   band against page-wide pixel occupancy — a stricter, contradictory
   criterion. Every page came back single-column. Fix: measure the band with
   the same test that selected it.
2. **Strict ascending field numbers silently dropped fields.** The closing
   admin block is two-column, so the stream reads `25. … 28. …` then
   `26. … 29. …`; requiring ascending numbers discarded fields 4–7, 26, 27 and
   29 on most reports. Fix: accept on label match, suppress duplicates, and
   treat out-of-order as an informational anomaly.
3. **`Flexi-Coil` parsed as a cause category.** A separator alternative
   `(?<=[a-z])-(?=[A-Z])` split ordinary hyphenated compounds, inventing a
   category `The Flexi`. Fix: an ASCII hyphen is a separator only when followed
   by whitespace.

**Extraction rate, n=63 stratified sample:**

| Field | Located | Non-empty |
|---|---|---|
| 17 Investigation Findings | 63/63 | 63/63 |
| **18 Probable Cause(s)** | **63/63** | **63/63** |
| **19 Contributing Cause(s)** | **63/63** | **58/63** |
| 22 Recommendations | 59/63 | 57/63 |
| 4 Lease/Area/Block | 63/63 | 63/63 |

0 parse failures, 0 files without a text layer. Fields 8–16 are missing on 10
reports and field 29 on 40 — a known remaining gap in form-face parsing on
older layouts, not yet chased because fields 17–24 carry the project's payload.

---

### Task 4 — cause vocabulary induction

**Method.** Induction was run **vocabulary-blind**: the parser extracts any
category-like prefix (≤6 words, title-ish, preceding the first `:` / `–` / `- `)
without consulting a category list. Had it matched against the six categories
from the brief, the "induced" vocabulary would just be those six reflected back.

**Sample:** 63 reports, stratified across 2014–2026, all six districts.
82 typed cause statements from fields 18 and 19.

**Result — the vocabulary collapses. 82% onto exactly six categories:**

| n | Category |
|---|---|
| 20 | Equipment Failure |
| 19 | Human Performance Error |
| 11 | Management Systems |
| 7 | Communication |
| 5 | Supervision |
| 5 | Work Environment |

**The remaining 18% is 14 distinct phrases, every one a singleton, and every one
a *subcategory* used without its parent** — `improper hand placement`,
`failure to follow safety protocols`, `lack of job safety analysis`,
`no stop work intervention`, `flawed equipment design`. These are not new
categories; they are level-2 terms appearing bare. That is a strong signal the
taxonomy is real and that authors sometimes skip the top level.

**Correction to the brief:** the dominant label is **"Human Performance Error"**
(19 occurrences), not "Human error" (which appears as a minority variant).
Anything keying on the string `Human error` will miss most of the category.

**Subcategory level is NOT yet shown to be closed.** Observed subcategories are
sparse — mostly 1–4 distinct per category at n=63 — and BSEE wording drifts
(`Inadequate equipment maintenance or equipment repairs` vs
`Inadequate preventative maintenance/Inadequate equipment repair`). Determining
whether level 2 is closed needs a substantially larger sample. **Do not assume
it is.**

### Where the typing boundary actually falls — temporal, not district

Bucketed on the incident date **inside the PDF** (field 1), not the filename —
filename years are unreliable, see below.

| Incident year | n | typed | % typed |
|---|---|---|---|
| 2014 | 4 | 1 | 25% |
| 2016 | 4 | 0 | 0% |
| 2018 | 7 | 3 | 43% |
| 2019 | 2 | 1 | 50% |
| 2020 | 4 | 1 | 25% |
| 2021 | 6 | 1 | 17% |
| **2022** | 6 | 5 | **83%** |
| 2023 | 7 | 6 | 86% |
| 2024 | 8 | 5 | 62% |
| 2025 | 7 | 6 | 86% |
| 2026 | 6 | 4 | 67% |

Collapsed: **2014–2021 = 7/27 typed (26%)**, **2022–2026 = 26/34 typed (76%)**.

| District | n | typed | % typed |
|---|---|---|---|
| New Orleans | 21 | 12 | 57% |
| Houma | 10 | 6 | 60% |
| Lake Charles | 4 | 2 | 50% |
| Lafayette | 13 | 5 | 38% |
| Houston | 2 | 2 | 100% |
| Unknown | 13 | 6 | 46% |

**Verdict: the boundary is temporal.** It falls at **2021→2022**, earlier than
the 2023–24 the brief hypothesised. The district hypothesis is not supported —
the four districts with usable n span 38–60%, a narrow band with no district
near 0% or 100%, while the temporal split is 26% vs 76%.

**Important qualifier: it is a gradient, not a switch.** 2022+ is ~76% typed,
not 100%, and 2018 was already 43%. Typing looks like a **practice that
spread**, not a form revision. Practically: **you cannot filter by year and
assume typed.** Every record needs its `cause_status` checked individually.

Caveats on this table: per-year n is 2–8, so individual years carry wide
intervals; the collapsed 26%-vs-76% split is the load-bearing claim, not any
single year. District was inferred by regex over narrative text and is
`UNKNOWN` for 13 of 63.

---

### Task 3 — corpus scope (harvest)

The "342 links, 2018–2026" figure in the brief understated the corpus in both
directions. `data/manifest.csv` holds **1,303 reports**: **1,241 district** +
**62 panel**.

Coverage reaches back to **2003**, because the district index has a **second
page** — a `district-investigation-reports-archive` — that the brief did not
account for. Split by index page: 591 rows from the main district page, 650
from the archive, 62 from the paginated panel listing.

Per-year counts on the archive side (2003:3, 2004:16, 2005:58, 2006:88,
2007:97, 2008:88, 2009:77, 2010:38, 2011:39, 2012:80, 2013:64, 2014:71,
2015:70, 2016:48, 2017:46) confirm the index's own "since 2005-01-01" claim and
slightly exceed it. 59 rows have no parseable year and carry a
`src_parse_note`; no row was dropped.

28 rows flagged redacted; 11 required URL canonicalisation. 635 of 1,303 rows
carry a non-empty `src_parse_note` — filenames are far more irregular in the
2003–2013 archive than in recent years, so filename-derived area/operator/date
should be treated as a convenience field only. **The authoritative values are
inside the PDF** (form fields 1, 2 and 4).

Spot-checked extraction against five archive-era reports (2006, 2007, 2011,
2017, 2023): all five parsed, all five located field 18 with non-empty content,
and **all five were `freetext`** — an independent confirmation of the temporal
typing finding on documents outside the induction sample.

### Corpus-level gotchas found in passing

**Filename years lie.** `2010` in a BSEE filename is usually the **form
number**, not a year — these are MMS **Form 2010**, and it leaks in as
`EV2010`, `EV2010R`, `2010_Report`, trailing `-2010`. Confirmed examples:
`W_&_T__HI_A_379-B_2010_Report_21-Feb-2024.pdf` is a 2024 report;
`gb-426-31mar19-sanitized-2010.pdf` is 2019. A last-4-digit-year heuristic
produces a spurious 2010 cohort. Parse a **date token**, and fall back to the
in-PDF field 1 date, which is authoritative.

**9 of 576 published PDF links (~1.6%) are dead as published.** They point at
`bsee_prod.opengov.ibmcloud.com`, which does not resolve (SERVFAIL; the
hostname contains an underscore, invalid in DNS). All recover by canonicalising
to `https://www.bsee.gov/sites/bsee.gov/files/<basename>.pdf` — verified
returning HTTP 200 for three of them. Two further links point at
`connect.bsee.gov` and an Acquia staging host. The manifest records both the
as-published href and the canonical fetch URL, because silently rewriting a
broken link would defeat the provenance standard.

**Redactions are undercounted by the obvious test.** 15 of 576 current district
PDFs are redacted, with inconsistent naming (`_Redacted`, ` redacted`,
` Redacted`, mid-filename); `endswith("_Redacted.pdf")` catches about a third.
The 2003–2013 archive has 0 of 656 marked, which is ambiguous between "never
reviewed" and "redacted without the convention" — treated as **unverified for
PII**, not clean.

**Dirty data left dirty**, per convention: BSEE stamps approval dates as
free-floating text that lands *inside* field 18 in visual order (e.g. a stray
`15-JUN-2021` between a category and its description). These are filtered as
page furniture at parse time, and the filter is declared in
`schema/bsee_form2010.yaml` rather than hidden in code.

---

### What is not yet verified

- Whether the level-2 subcategory vocabulary is closed (needs n >> 63).
- Panel-report joinability to the spine — not measured.
- Whether the Xls/Xlsx/Pdf/Rtf grid exports carry a wider column set than CSV.
  They render from the same server-side `ASPxGridView`, so a wider set is
  implausible rather than ruled out.
- Form-face fields 8–16 on ~16% of reports and field 29 on ~63%.
- The 2003–2013 archive has not been extracted, only counted.

## 2026-08-09 — Resolving the coverage fork (labeling vs. free-text handling)

**The fork was a false dichotomy.** Since the vocabulary induction (Task 4,
above) confirmed the extraction premise but left ~68% of the corpus as
free-text prose with no controlled cause vocabulary, the open question was
whether to (a) hand-label the gold set now against the ~32% typed subset, or
(b) first build an LLM-assisted path for the free-text majority. Gold-set
construction does not actually depend on that answer: a human labeller reads
the source PDF directly and assigns `gold_` fields regardless of whether
field 18/19 happened to use the controlled vocabulary. `src_cause_status` is
recorded per report for reference, not as a gate on whether a report is
eligible for the gold set. Building the gold set first is also the right
sequencing on its own merits — it is the fixed yardstick any future
extraction approach (crosswalk-only or LLM-assisted) gets evaluated against;
designing the extraction approach before the eval set exists risks shaping
the eval set around whatever the approach happens to handle well.

**Resolution:** proceed with gold-set construction now, stratified across
the full 2003–2026 corpus (typed and free-text eras alike), not just the
typed subset. The LLM-assisted free-text path is deferred, to be built and
scored against this gold set once it exists — not before.

**What was built**, per Task 5 of the original brief (100 reports,
stratified across years):

- `src/psm/gold_sample.py` — deterministic, year-stratified sampling from
  `data/manifest.csv`. District reports only (`src_report_type ==
  "district"`); panel reports are excluded because they are a structurally
  different, unverified document type (see "not yet verified" below) that
  this project's extraction pipeline was never built against. Selection
  within each year is by ascending `sha256(src_url)` — no stored seed, same
  determinism pattern as `src/psm/synth.py`'s hash offsets. Allocation is
  `target_n // n_years` per year, floored at 1 and capped by that year's
  availability, remainder distributed to the years with the most spare
  capacity. Run against the real manifest: **100 of 1,302 rows selected**,
  every year 2003–2026 represented (2003 capped at 3 — only 3 district
  reports exist for that year), the rest 4–5 each.
- `src/psm/gold_scaffold.py` — assembles `gold/gold_labels.csv` from the
  sampled manifest plus `extract.py`'s per-report JSON: one row per sampled
  report with `src_` reference fields (operator, area/block, date, url,
  field 18/19 raw text) pre-filled, and `gold_cause_category` /
  `gold_psm_element` / `gold_cause_status` / `gold_notes` / `gold_labeler` /
  `gold_label_date` left **blank by design**. This module never writes a
  `gold_` value — doing so would collapse the `gold_`/`llm_` distinction the
  whole provenance convention exists to protect. `src_cause_status` is
  computed per row (typed wins if either field 18 or 19 is typed; freetext
  wins over absent/parse_failed; `absent_legitimate` only when both fields
  are genuinely blank) purely as a reference hint for the labeller, with the
  caveat below.
- Fetched the 100 sampled PDFs (`uv run python -m psm.fetch --manifest
  data/interim/gold_sample_manifest.csv`) — 100/100 downloaded, 0 failures.
  Extracted all of them (`extract.py`) — 104/105 `ok` (105 = 100 sample + 5
  pre-existing dev-sample files already in `data/raw/`), 1 `parse_failed`.
  `gold/gold_labels.csv` now has 100 rows: **29 typed, 70 freetext, 1
  parse_failed** by the automated classifier — see the caveat immediately
  below before treating that split as authoritative.

**Caveat — `src_cause_status` on this sample has a known false-positive
mode, do not cite the 29/70/1 split as clean.** Verifying a 2003 report
flagged `typed` found the actual field-19 text was 100% free prose;
`candidate_category()` (`src/psm/causes.py`) matched on `"NOTE:"` and
`"LIST THE ADDITIONAL INFORMATION:"` — continuation-page furniture bleeding
into the field-19 text run from a multi-page narrative, not real BSEE cause
categories. Reproduced directly:
`candidate_category("NOTE: ABB Vetco has redesigned...")` returns
`("NOTE", "colon")` instead of `(None, "untyped_prose")`. This means the
true free-text share of this sample (and likely the corpus) is **at least
70%, plausibly higher** — the bug only pushes reports *into* `typed`, never
out of it. Flagged as a follow-up task, not fixed here, to keep this session
scoped to resolving the fork rather than re-opening the vocabulary-induction
parser. `gold_cause_status` (human-assigned) is not affected by this bug —
only the `src_cause_status` reference column is.

**Not yet done:** the actual hand-labeling. `gold/gold_labels.csv` is a
scaffold — 100 rows with real reference data and empty `gold_*` columns,
not 100 labelled examples. README's status table has been updated to say so
explicitly rather than implying the file is already labelled.

## 2026-08-09 — Fixing the `candidate_category()` furniture false positive

Follow-up to the caveat immediately above. Root-caused before fixing, per the
project's debugging discipline: scanned every typed statement across the 194
non-empty field-18/19 texts currently cached in `data/interim/` (the 100-report
gold sample plus a few pre-existing dev files) for every head `candidate_category()`
currently accepts. 41 distinct heads matched; two are furniture, not categories:

- `NOTE` (2 occurrences, both in `030521-pdf` — a continuation-page annotation)
- `LIST THE ADDITIONAL INFORMATION` / `LIST THE CONTRIBUTING CAUSE(S) OF ACCIDENT`
  (3 occurrences, `030521-pdf` and `mc-194-enven-20-jan-2020`) — a field's own
  BSEE label bleeding into another field's body text.

The other 39 (Equipment Failure, Human Performance Error, Management Systems,
Communication, Supervision, The IP, The Root Cause, Policy Violation, etc.) are
genuine BSEE cause language and must not be touched. `(Cont.)`-style markers
were already correctly rejected by the existing `head[0].isalpha()` check — no
fix needed there.

**Fix** (`src/psm/causes.py`): added `FURNITURE_HEAD_RE` (`^(?:NOTE|LIST\s+THE\b.*)$`,
case-insensitive) and a check in `candidate_category()` that returns
`(None, "furniture")` for a match, instead of treating it as a typed category.
`LIST\s+THE\b.*` is scoped to BSEE's own field-label phrasing (field 18 is
literally "LIST THE PROBABLE CAUSE(S)") rather than hardcoding field 20's
exact wording, so it generalises to any field's label bleeding into another —
confirmed by the `mc-194-enven` case above, which uses field 19's own label,
not field 20's.

**Regression tests** added to `tests/test_causes.py`: the two furniture
patterns, a cross-field generalisation case, a field-level
`classify_field()` case reproducing the full `030521-pdf` false positive, and
a negative case (`"Listing errors: ..."`) confirming the guard doesn't
collide with real categories. Full suite: 142/142 pass.

**`gold/gold_labels.csv` regenerated** (`uv run python -m psm.gold_scaffold`;
no hand-labels existed yet, all `gold_*` columns were blank, so nothing was
at risk). Exactly one row changed — `030521-pdf` (report
`d34a71a29a8cf864f4c8af727bc4249954300d2f0e7c640162aa04dc4851a9fe`), whose
`src_cause_status` flips from `typed` to `freetext`, matching the diagnosis.
New split: **28 typed, 71 freetext, 1 parse_failed** (was 29/70/1).

**Effect on the two corpus-wide numbers flagged for review:**

- **"82% of typed statements collapse to 6 categories" (Task 4, n=63,
  above).** Not reproducibly affected — none of its reported categories or
  the 14 singleton subcategories look like furniture, and the fix is scoped
  to two patterns neither of which appears in that table. But this could not
  be fully re-verified: the original n=63 file set for Task 4 was not
  preserved separately from the current `data/interim/` cache, so it is
  unclear whether it is a subset of the 194 texts scanned above. Treat the
  82% figure as **unaffected but unverified against this specific fix** —
  re-running Task 4's induction against its original file list, if
  recoverable, is a follow-up, not done here.
- **"~32% typed subset" (fork-resolution entry, above).** This was
  approximate framing, not a precise citation of the pre-fix 29/100=29%
  gold-sample figure. Post-fix it is **28/100 = 28%** typed by the automated
  classifier. Read this as a **soft ceiling, not a clean number**: only two
  furniture patterns were confirmed and fixed from one 100-report sample —
  other BSEE field-label fragments (e.g. from fields 17, 21–24) could still
  be bleeding into 18/19 undetected on reports outside this sample. The
  true typed share is `<= 28%`, direction unchanged from the original
  caveat (the bug only ever pushes reports *into* `typed`).

## 2026-08-29 — E19 label extraction: the target schema does not match the template

**Why this was run.** Adversarial review of a worked E19 sample found the field
names did not match the source workbook. The same defect turned out to be in the
repo: `schema/e19_target.yaml` is hand-written with invented snake_case names
(`incident_date`, `area_block`, `narrative_summary`) rather than the template's
actual labels. It is explicit about this — *"HAND-WRITTEN. No workbook was
opened, copied, or derived from"* — a deliberate IP-safety choice that
nonetheless leaves the schema unable to satisfy an exactness requirement.

**Decision taken:** add an **E19 projection layer** rather than rename
throughout. The internal snake_case schema stays canonical for the pipeline;
exactness becomes a property of the output. `synth.py`, `gold_scaffold.py` and
`crosswalk.yaml` are untouched.

### What was built

`src/psm/e19_schema.py` — reads the workbook **read-only** and emits
`schema/e19_labels.yaml`. Labels are never retyped: every field-name mismatch
found in review so far came from a human transcribing them. The workbook itself
remains uncommitted; the derived YAML (names and vocabularies only, no formulas
or rollup logic) is committed, consistent with CLAUDE.md's existing allowance.

Block detection is derived, not hardcoded to row numbers: the sheet's
convention is *header cell, blank row, contiguous field run*, so a run of length
one is a header and the following run is its fields. Survives a row insert.

**Result: 7 groups, 65 fields, 29 vocabularies.** Workbook SHA256 asserted
unchanged across the run. A round-trip check re-opens the workbook and compares
every emitted label and value against its source cell.

### Two extractor bugs the round-trip check caught before commit

Both produced plausible, non-erroring output — the failure mode this project
keeps hitting.

1. **`Risk Score` came out with 45 values.** Column W stacks `1..25` (the real
   risk-score vocabulary) immediately followed by `1..20` (PSM element numbers)
   with no blank row between. Read naively that is one 45-value vocabulary. Fix:
   split a column where a numeric series restarts. `Risk Score` is now n=25 and
   the trailing `1..20` is emitted separately.
2. **Values were assumed contiguous.** Several picklist columns have blank rows
   inside them, so verifying against `first_row + i` failed on eight columns.
   Fix: store each value's actual row rather than inferring a range.

A third issue is handled rather than fixed: five columns have no header of their
own (`X45`, `AI6` are bare PSM element lists; `W45`, `BF7`, `BH7` are numeric
scales). Their first cell is a *value*, not a name. Rather than invent a
vocabulary name, these are emitted with `name: null` and
`header_confident: false`, leaving identification to the consumer.

### Template irregularities, preserved verbatim

These are the real column names. Normalising them would defeat the exactness
guarantee: `Incident Classificatioin` (sic, used twice), `incident Title`
(lower-case i), `Unmittigated` / `Mittigated` (sic), `Human Factors  Cause`
(double space), ` Failed PSM Framework Element` (leading space),
`What happened?  ` (two trailing spaces), `Health & Safety  - Consequence`
(double space, and the sibling E&R and Financial fields differ from each other
in the same way).

**`Description` appears twice in one group** (E18 and E23 — the form's two
"Description if Other" fields). A flat table cannot carry two identically named
columns; the projection must disambiguate, and how it does so needs the author's
input rather than our invention.

### Diff against `schema/e19_target.yaml`

| | n |
|---|---|
| E19 fields total | 65 |
| Covered 1:1 by a differently-named target field | 33 |
| Partially covered — grain or split mismatch | 9 |
| **Absent from the target schema entirely** | **23** |
| **Name matches between the two schemas** | **0 of 65** |

Partial coverage is where the shapes genuinely differ: E19 splits location into
`Site` / `Area` / `Unit` / `Detail` where the target has one `area_block`; E19
has four `Incident Type A–D` fields where the target has one multi-enum;
`Cause Description` and `Recommendation Description` are one-row-per-item in E19
against list-valued fields in the target.

The 23 absent fields cluster in three places: **the consequence/likelihood pairs
for all three risk matrices** (the target kept only the scores), **the cause
qualifiers** (`Cause type`, `Risk Management Cause`, `Human Factors  Cause`), and
**the row keys** (`Cause number`, `Recommendation Number`).

13 target fields have no E19 counterpart at all — `lease_number`, `operator`,
`water_depth_ft`, `activity`, `operation`, `property_damage_usd`,
`regulatory_violations`, `cause_category`, `cause_status`, and others. These are
BSEE-side or project-side fields and belong in the sidecar, not in E19 output.
Note E19 has no `operator` field at all, which makes sense for an internal
company form where the operator is implicit.

**Not yet done:** `schema/e19_projection.yaml` (the mapping itself, including
blank-reason codes), `src/psm/project.py`, and the exactness test asserting
output headers equal the labels read from the template.

## 2026-08-29 — Root cause of the archive-era extraction gap

Two independent investigations, run in parallel against the same 105 raw PDFs
and 105 interim JSONs. They converged on one mechanism from different angles,
which is the main reason to trust the conclusion.

### The headline: the narrative is present and recoverable

**The archive-era field-17 gap is a parser bug, not missing data. The gold
sample does NOT need to be re-drawn.** Re-running the real `extract_report()`
with *only* field 17's `label_hint` relaxed recovered clean, complete narrative
prose (545–3,892 chars) from **22 of the 23 failing files**.

The 23rd is not our bug: `data/raw/090517-pdf.pdf` **is not an investigation
report**. Its PDF title is *"MMS to hold Public Hearings on Cape Wind Energy
Project Draft Environmental Impact Statement"* — a 2008 press release served at
an incident-report URL. `parse_failed` is the correct outcome; the parser
refused rather than inventing fields. Upstream data defect, log it.

### Root cause 1 — the form has three numbering eras; the schema encodes one

`schema/bsee_form2010.yaml` states *"Field numbers are stable across eras; LABEL
WORDING IS NOT."* **The first half is false**, and it is the largest single
cause of damage across the corpus.

| Era | n | Years (in-PDF field 1) | Numbering vs schema |
|---|---|---|---|
| A early | 12 | 2004–2006 | no field 3; everything from LEASE on shifted −1 |
| B mid | 53 | 2003–2017 (mode 2007–2016) | 1–7 match; **9–16 shifted −1** |
| C modern | 38 | 2017–2026 | exact match |

Field 17's label also changes: the older revision reads
`17. DESCRIBE IN SEQUENCE HOW ACCIDENT HAPPENED:` where the modern one reads
`17. INVESTIGATION FINDINGS:`. The correlation is perfect across all 105 files —
81/81 located under the modern wording, **0/22** under the old.

**Why it fails silently.** Content runs anchor-to-next-anchor. When
`_label_matches()` rejects an anchor, that field's content is absorbed into the
*previous accepted* field rather than being dropped. Verified: `070822-pdf` has
`src_f07_type` at **2,356 chars** holding fields 8–16 plus the whole narrative;
`060411-pdf` has `src_f02_operator` at **2,556 chars** holding most of the form
face. A `checkbox_set` field silently containing prose is worse than an empty
column.

One thing the hint gate gets right: a shifted anchor never produces *wrong
content under a right name*. The failure is absence-plus-absorption, not
mislabelling. No `src_f10_water_depth` anywhere contains a non-depth.

**Correction to a previous entry.** "Fields 8–16 missing on 10 reports, field 29
on 40 — a known remaining gap in form-face parsing on older layouts" (2026-08-02)
misdiagnosed this. f08 is present on exactly the 38 modern-era reports; the other
67 did not fail to parse, their content was absorbed.

### Root cause 2 — `find_gutter()` fails on the closing admin block

Page 0 gutter detection succeeds 104/105. The admin page (the one with
`DISTRICT SUPERVISOR`) succeeds **31/105**. Without a gutter, left and right
columns merge into single rows — `bp-mc-778-a-6-june-2022.pdf` p3 emits
`25. DATE OF ONSITE INVESTIGATION: ACCIDENT CLASSIFICATION:` as one line, which
is exactly the f28→f25 bleed originally reported.

### Root cause 3 — `ROW_TOL` is a hard bin edge, not a tolerance

`_rows()` buckets on `round(top/2.5)`, so words 0.5pt apart can land in
different bins when they straddle a boundary. `25. …` (top 275.9 → bin 110) and
`28.` (top 276.4 → bin 111) split; the orphan `28.` then fails `ANCHOR_RE`.
**41 orphan `NN.` lines across 27 records**; records with an orphan lose f28
21/27 of the time.

### Root cause 4 — the terminal anchor is an unbounded sink

`segment_fields()` runs the last anchor to end-of-document. **48/105 reports
have pages after the admin page** (injury, witness, crane attachments). f30
median length is 35 chars, p90 is 1,290; `vr-131-stone-energy-17-september-2012`
holds **6,049 characters** in a field that should contain one name.

### Contamination by field — the payload is clean, the metadata is not

Rate = records whose value contains ≥1 label owned by a different field.

| Field | n | contaminated | severity |
|---|---|---|---|
| f17 findings | 82 | **0%** | clean where present |
| f18 probable cause | 104 | **0%** | clean |
| f19 contributing cause | 103 | **1%** | clean |
| f22 recommendations | 95 | **0%** | clean |
| f04 lease/area/block | 92 | 1% cross-field | but **97% intra-box misalignment — meaning-changing** |
| f07 type | 91 | **58%** (100% of era B) | severe; median 45% of value is foreign |
| f26 team members | 103 | **70%** | severe; **55% *begin* with a foreign label** |
| f30 district supervisor | 93 | **53%** | severe; real name at start, unbounded tail after |

**The project's payload fields (17–24) are essentially uncontaminated. The
damage is concentrated in identification (4, 5, 7) and the admin block (25–30).**

A separate universal but **cosmetic** class: own-label retention. When an anchor
line has no colon the label-strip does not fire and the field keeps its own
`NN. LABEL` — f01 100%, f03 100%. f01 still yields a parseable date on 101/103.

### `out_of_order_anchor` is a success indicator, not a warning

30/105 records carry it. f26 is contaminated on 9/30 records that have it versus
**63/73** that do not. The anomaly fires when the admin columns *were* split
correctly (left 25,26,27 then right 28,29,30 — legitimately out of order). Any
triage keyed on this flag would select the healthiest records. Do not use it as
a quality signal.

Genuinely predictive flags, none currently logged: form era (derivable from
which number carries `WATER DEPTH`); gutter-not-found on the admin page;
presence of an orphan `NN.` line; pages existing after the admin page.

### Downstream exposure — latent, not yet propagating

`gold_scaffold.py` is the only consumer of any `src_fNN_` column and reads
exactly two: f18 and f19, both clean. Its area/block/operator come from
`data/manifest.csv`, not from f02/f04. `synth.py` reads no `src_f*` at all.
`causes.py`'s `FURNITURE_HEAD_RE` is scoped to 18/19 and masks nothing found
here.

**One forward-looking trap.** The 2026-08-02 entry commits to *"The
authoritative values are inside the PDF (form fields 1, 2 and 4)"* as the remedy
for unreliable filename-derived metadata. As of today f04 is misaligned on 97%
of records and f02 is a whole-form dump on all 12 era-A records — the designated
authoritative source is currently the worse of the two options. Do not act on
that recommendation until root cause 1 is fixed.

### Verified vs inferred

**Verified** by opening PDFs and re-running layout/extraction over all 105:
text layers present on 105/105 (no OCR needed anywhere); the `DESCRIBE IN
SEQUENCE` wording and its 81/81 vs 0/22 correlation; the three-era numbering
table (53/53 and 10/10 within cluster); gutter 31/105 admin vs 104/105 page 0;
41 orphans / 27 records; 48 records with post-admin pages; the
`out_of_order_anchor` anti-correlation; the 22/23 recovery with zero regression
on field 18; `090517-pdf` being a press release; the downstream consumer
inventory.

**Inferred:** corpus-wide exposure of roughly **300–350 reports** with the old
field-17 wording, extrapolated from 30 downloaded 2004–2009 files against
manifest per-year counts. The label→owning-field map used for intrusion
detection is a reading of the form's box structure, not a published source.

**Could not check:** the ~1,140 reports not in `data/raw/`; whether more than
three revisions exist pre-2003 or among panel reports; whether recovered
narratives contain the sub-structure the schema expects.

**A methodological note worth keeping.** An early `pdftotext -layout` pass
suggested 2007-era files swap fields 6/7. The coordinate-aware read shows they
do not — a pdftotext column-ordering artifact, and a clean illustration of why
CLAUDE.md forbids the text path for field assignment.

## 2026-08-29 — P0 remediation landed

Implements P0 of `docs/superpowers/plans/2026-08-29-extraction-remediation.md`.
Measured before/after on the same 105 PDFs and the same era split used in the
diagnosis.

### Result

| Check | Before | After |
|---|---|---|
| Archive-era (2003–2013) field 17 fill, gold sample | 26/48 = **54.2%** | 47/48 = **97.9%** |
| Current-era (2014–2026) field 17 fill | 52/52 = 100% | 52/52 = 100% (no regression) |
| Records carrying `src_form_revision` | 0 | 105/105 |
| Test suite | 142 | 159 |

The one remaining archive miss is `090517-pdf`, which is not an investigation
report — see below. **The gold sample is now labellable across both eras.**

### What changed

**Field 17 label alternates.** `label_hint` now accepts a list; a list matches
if any alternate is present. Added `DESCRIBE IN SEQUENCE` for the pre-2010
wording. Roughly the 10-line change the diagnosis predicted.

**`src_form_revision` on every record.** Detected from the raw anchor stream,
not from extracted fields — on revisions A and B the deciding anchors are
rejected by the label hints, so by the time `fields` exists the evidence has
been discarded. Distribution across the 105: **A 13, B 53, C 38, unknown 1**.
The agent diagnosis predicted 12/53/38; the extra revision-A record is a
one-file discrepancy not chased, and the `unknown` is the press release.

**Length-sanity guard.** Flags structured fields holding far more text than
their kind allows. Raises an anomaly and never truncates, per the dirty-data
convention.

**`not_an_investigation_report` status.** A text layer with no Form 2010
markers is now distinguished from `parse_failed`. Generalised on markers rather
than hardcoding the filename, so any future non-report URL is caught. Confirms
`090517-pdf`, which BSEE serves as a 2008 MMS press release at an
incident-report URL.

### The length guard was calibrated wrong on the first attempt — worth recording

The initial thresholds fired on **104 of 105 records**, which is a guard that
says nothing. Root cause: a 400-char `checkbox_set` cap, where revision-C field
7 runs a legitimate **median of 533 chars** of checkbox labels and maxes at 562.
All 38 correct records tripped it.

Recalibrated against **revision C as the baseline**, since that is the only era
where extraction is known correct: each cap now sits above revision C's observed
maximum with headroom.

| | Before | After |
|---|---|---|
| Records tripping the guard | 104/105 | **66/105** |
| Revision-C firings (false positives) | 38 | **0** |

Firings after recalibration, by revision:

| Field | A (n=13) | B (n=53) | C (n=38) |
|---|---|---|---|
| 2 operator | 12 | 0 | 0 |
| 7 type | 1 | 52 | 0 |
| 30 district supervisor | 6 | 18 | 0 |
| 27 operator report | 0 | 3 | 0 |
| 6 activity | 0 | 1 | 0 |

Every firing is on revision A or B, exactly where absorption was diagnosed, and
none on C. The distribution independently corroborates root cause 1: field 7
absorbing content on 52 of 53 revision-B records is the fields-8–16 shift, seen
from the other side.

**The generalisable lesson:** calibrate an integrity check against the subset
where the pipeline is known correct, then confirm it stays silent there. A
threshold picked by intuition fired on 99% of inputs and would have been noise
from day one.

### Not fixed here, unchanged from the plan

P1 per-revision field map (fields 3–16 remain rejected on revisions A and B,
their content still absorbed). P2 admin-block gutter, terminal-anchor sink,
`ROW_TOL` bin edges. P3 field 4 intra-box alignment. The `src_form_revision`
column now makes all three testable by era.

`schema/bsee_form2010.yaml`'s header comment previously asserted *"Field numbers
are stable across eras"*. Corrected — it is false, and it is the reason this
class of bug went unnoticed.

## 2026-08-29 — E19 projection: what BSEE can actually fill

Delivers the verbatim E19 mapping. Four relational tables whose column names are
byte-exact E19 field labels, read from `schema/e19_labels.yaml` at runtime and
never hardcoded. Nothing is crosswalked, inferred or synthesised.

### Output

| Table | rows | cols |
|---|---|---|
| `incidents.csv` | 104 | 43 |
| `causes.csv` | 330 | 7 |
| `recommendations.csv` | 93 | 12 |
| `closeout.csv` | 93 | 4 |
| `bsee_unmapped.csv` (sidecar) | 104 | 15 |

### The headline number

Of the **65 E19 fields**:

| | n |
|---|---|
| **Populated from BSEE** | **23** |
| Had a source but returned nothing | 0 |
| Blank — `judgement` (needs a human) | 27 |
| Blank — `structural` (nothing in the document answers it) | 13 |
| Blank — `extractable` (in field 17 prose, phase 2) | 2 |

Fill rates on the populated 23 (n=104 incidents):

| Field | fill |
|---|---|
| Incident Number, How did the incident occur, What happened? | 100% |
| Date of Incident | 97.1% |
| Investigation leader - Name | 95.2% |
| Site | 93.3% |
| Time of Incident, Description, Acceptor/Approver Name + Position | 87.5% |
| Area | 84.6% |
| Unit | 60.6% |
| Detail | 33.7% |
| Incident Classificatioin / Incident Classification | 23.1% |

`Detail` and `Incident Classificatioin` are genuinely thin in the source — rig
name and field 28 are frequently blank on the form itself — not extraction
failures.

### Two extractor decisions worth recording

**`What happened?` was 14.4% on the first run.** Keying on an explicit
`INCIDENT SUMMARY` heading found only 15/104, because most reports do not print
one. Where the heading is absent the opening of the narrative *is* the summary,
so the rule now takes everything before the first later subheading. **14.4% →
100%.**

**`How did the incident occur` deliberately returns blank** when a report has no
`SEQUENCE OF EVENTS` heading, giving 23.1% rather than 100%. Falling back to the
whole narrative would copy `What happened?` into both columns and imply a
separation the document does not make. Accuracy over coverage.

### Design notes

`schema/e19_projection.yaml` carries one entry per E19 label, each with either a
`source` or a `blank` reason code — enforced by test, so no field can be silently
absent. Tests also assert the mapping invents no field the template lacks, and
that emitted headers equal the template's labels as a set.

**`Description` appears twice** in Incident Information (E18 and E23, the form's
two "Description if Other" fields). A flat table cannot carry two identically
named columns and both would draw from the same BSEE source, so they collapse to
one, recorded under `collapsed_duplicates`. Needs the template author, not our
invention.

`Investigation Acceptor/Approver (Owner)- Position` is filled with the literal
`"District Supervisor"` when field 30 is non-empty — the field's own label is the
position. Borderline between a source value and an inference; flagged in the map
rather than presented as clean.

Names are pseudonymised at projection time with a committed salt (`INV-xxxxxx`,
`SUP-xxxxxx`), stable per person corpus-wide.

### Caveat

Incident Number is `{AREA}-{BLOCK}-{YYYYMMDD}-{HHMM}`, constructed because BSEE
publishes no identifier. Zero collisions across 104 records. But area/block are
parsed from field 4, which the contamination audit found misaligned on 97% of
records — a targeted regex recovers them at 93%/85%, well above what positional
parsing would give, yet at least one key looks wrong (`LB-6488-...`, where `LB`
is likely "Lift Boat" rather than an area code). **Treat the key as stable and
unique, not as a clean location reference**, until P1 and P3 land.

## 2026-08-29 — Session 1 crosswalk, and a severity bias in the corpus

Applied `schema/xw_incident_type.yaml` via new `psm.crosswalk`. Output is a
separate enriched copy plus a cell-level provenance table, so inferred values are
never mistaken for read ones.

| Field | filled by crosswalk |
|---|---|
| Incident Type A | 1,037 / 1,215 = **85.3%** |
| Incident Type B | 784 = 64.5% |
| Incident Type C | 716 = 58.9% |
| Incident Type D | 233 = 19.2% |

13,136 `src` cells against 2,770 `xw` cells. Type D is low by choice: Crane and
Other Lifting Device (271 records) resolve to null because they name equipment,
not mechanism.

### Three resolutions reached by checking rather than asking

**`Injury TLI`** is defined nowhere public, and this workbook is not an EI
publication, so it may be the author's own abbreviation. It does not matter:
BSEE's `LTA` means *days away from work* and `RW/JT` means *restricted work or
job transfer*, so aligning the ladders puts LTA in slot three regardless of what
TLI expands to. Both LTA duration bands map there; BSEE's 1-3 vs >3 split has no
E19 counterpart.

**Bare `Injury` → null, not Minor.** A draft defaulted it to `Injury Minor`.
Narrative sampling killed that: 135 of 148 carry no severity atom, and the ones
that do co-occur with `Fatality` 12 times and never with a minor code. It reads
as an older tag predating the LTA/RW-JT vocabulary.

**`Crane` → Type D null.** A draft proposed `Dropped Object` as the modal case.
151 narratives show boom failures, an injury during a crane *inspection*, rigging
and positioning incidents, and loads lost overboard. A modal guess would be wrong
on a large minority of 177 records.

**`Injury Permenant Disability` is structurally unreachable.** BSEE classifies by
duration away from work; permanence is a different axis (IOGP maintains an FPI
framework, BSEE does not use it). No mapping effort reaches this value.

Precedence turned out to matter far less than expected: 39.4% of spine rows carry
2+ atoms, but only **36** carry two competing injury atoms, and response atoms
never compete for Type C.

### The finding that matters most: panel exclusion is a severity filter

`Injury Fatality` came out at **3 of 1,215**, against 85 `Fatality` rows in the
spine. Investigating that gap found a systematic bias:

| Accident type | spine n | PANEL | share |
|---|---|---|---|
| **Fatality** | 85 | 46 | **54.1%** |
| Blowout | 58 | 18 | 31.0% |
| Explosion | 74 | 5 | 6.8% |
| Pollution | 436 | 16 | 3.7% |
| Fire | 514 | 10 | 1.9% |
| Crane | 197 | 3 | 1.5% |

BSEE convenes a panel for death, serious injury or significant pollution — so
**panel reports are the high-severity tail**, and `psm.project` excludes them
because the extractor was never built against that document type. Excluding them
is right on parsing grounds and wrong on sampling grounds: it removes over half
of all fatalities and a third of blowouts.

**Any model trained on this corpus is trained on a corpus with the worst outcomes
systematically thinned.** That belongs in the README, not only here.

**Unexplained, flagged rather than buried:** 39 fatality incidents are DISTRICT,
not panel, so they should be reachable — yet only 3 join to `incidents.csv`. The
spine covers incidents while the manifest covers *published reports*, so some
spine rows may have no district report at all. Not yet verified.

## 2026-08-29 — Session 2: PSM element crosswalk re-based

`schema/crosswalk.yaml` v1 was keyed to a different element numbering than the
target template, for its whole life, uncaught. It routed Equipment Failure to
element **7** while its own note described *"maintenance, inspection and repair
adequacy"* — element 7 in the template is `Documentation, records and knowledge
management`; `Inspection and maintenance` is **15**. Applying v1 would have put a
wrong element on all 3,462 cause rows.

The reasoning in each note was sound. Only the anchoring was wrong, so v2
re-matches each note's own description against the template's element names and
records `matched_on` and `was_v1` per entry, making the re-basing auditable.

| Category | v1 | v2 | matched on |
|---|---|---|---|
| Equipment Failure | 7 (+10) | **15** (+11) | maintenance, inspection, repair adequacy |
| Human Performance Error | 13 (+12) | **3** (+8) | competence / human factors |
| Management Systems | 3 (+1) | **8** (+6) | no written job procedures / inadequate hazards analysis |
| Communication | 12 (+3) | **9** (+17) | shift handover, instruction, job briefing |
| Supervision | 13 (+3) | **17** (+3) | supervision of a task in progress |
| Work Environment | 10 (+7) | **6** (+11) | workplace layout, weather, marine environment |

**Supervision departs from v1's reasoning, not just its numbering.** v1 routed it
to the same element as Human Performance Error on adjacency grounds. The
statements describe a supervisor failing to enforce a defined procedure during
work in progress, which is work control rather than competency. Contested;
element 1 is also arguable. Left at low confidence.

**The trap avoided, now guarded by test.** Element 5 is `Communication with
stakeholders` — external and corporate. Matching the BSEE category
`Communication` to it on the shared word would route shift-handover failures to
stakeholder communication. `test_communication_is_not_element_five` asserts it.

### A coverage bug, separate from the numbering

v1's Human Performance Error note said *"Normalise before lookup"*. Nothing did.
The six keys matched only **54.1%** of typed statements: `human error` (64) and
`management system` (17) went unmapped **purely on spelling**.

An `aliases` block now implements what v1 already declared — and note this is not
the open Session 3 question about whether "human error" and "human performance
error" are the same concept. v1 answered that when it listed "Human error" as a
surface variant of the dominant form; the ruling was just buried in prose.

| | of typed statements |
|---|---|
| matched before aliases | 367 / 679 = 54.1% |
| matched after aliases | **451 / 679 = 66.4%** |

### Applied

`psm.crosswalk` now enriches causes as well as incidents, writing
` Failed PSM Framework Element` (the template's leading space preserved) with the
element number, plus `causes_provenance.csv`.

| | n | share of all statements |
|---|---|---|
| mapped | 451 | 13.0% |
| typed but unaliased | 228 | 6.6% |
| untyped free text | 2,783 | **80.4%** |

The 80.4% ceiling is unchanged by anything in this session and is not reachable
by crosswalking. It is the LLM-assisted path, which is downstream of a gold set.

`tests/test_crosswalk.py` (15 tests) asserts every element number resolves to a
real template element, that each entry records what it was before, and that the
incident-type values come from the template's own picklists.

## 2026-08-29 — Session 3: cause qualifiers

Three E19 fields: `Cause type`, `Risk Management Cause`, `Human Factors  Cause`.
Prep changed the shape of all three before any mapping was written.

### Level 2 is confirmed OPEN, not closed

`findings.md` flagged subcategory closure as unverified at n=63. At full scale it
is **open**: 309 statements carry a subcategory, long-tailed free text with
drift — `Inadequate preventive maintenance` / `Inadequate preventative
maintenance`, `Inadequate supervision` / `Inadequate Supervision` /
`No supervision`. Exact-string lookup would match the modal spelling and silently
drop the rest, so `schema/xw_cause_qualifiers.yaml` matches by **case-insensitive
substring pattern, first match wins**, with sharper rules listed before
catch-alls (guarded by test).

`(cid` also appears as a subcategory: CID-encoded text sitting *below* the 5%
guard threshold is leaking into cause statements. Small, but the threshold is
marginally too permissive.

### `Cause type` — deliberately unmapped

The only available signal is which BSEE field a statement came from: field 18
*Probable Cause* vs 19 *Contributing Cause*. That is an axis of **primacy**; E19's
Immediate / Underlying / Root is an axis of **depth**. A contributing cause can be
a root cause. Mapping one to the other asserts an equivalence that does not hold.

**A gap this exposed:** `psm.project` concatenates fields 18 and 19 without
recording which a statement came from, despite the projection plan saying it
would go to the sidecar. Real provenance is being discarded, and it is exactly
what an LLM-assisted pass would want as a feature.

### Results

| Field | filled | of 3,462 |
|---|---|---|
| ` Failed PSM Framework Element` | 451 | 13.0% |
| `Risk Management Cause` | 206 | 6.0% |
| `Human Factors  Cause` | 120 | 3.5% |
| `Cause type` | 0 | by policy |

### Human Factors: filled against my recommendation, and instrumented for it

E19's Human Factors classifies **cognition** (competency / mistake / violation);
BSEE subcategories describe **behaviour** (`Inattention to task`, `Placing hand
near striking point`). My recommendation was to leave the field null on the
grounds that inferring a cognitive mode from a behavioural description is
attribution dressed as data. **Session 3 ruled to map the full subcategory set.**

Implemented, with every pattern carrying a confidence and
`causes_confidence.csv` written to the sidecar so the two kinds can be told
apart. The split is the argument, quantified:

| confidence | n | what it means |
|---|---|---|
| high | 30 | the source names the cognitive mode (`not following procedures` → Violation) |
| medium | 36 | reasonably direct (`not aware` → missing information) |
| **low** | **54** | **attribution: the source names only what the person did** |

**45% of the values in this column are inference about mental state from a
description of behaviour.** They are marked, filterable, and `xw_` — never
scorable. Anyone using this column for analysis should filter on confidence
first, and anyone reporting a metric over it should not use it at all.

Human factors are scoped to human-attributable categories only; Equipment
Failure and weather subcategories get nothing, because there is no person in them
to attribute a cognitive mode to.

### Coverage ceiling, unchanged

80.4% of statements are untyped free text and no crosswalk reaches them. Of the
679 typed, 66.4% carry a mapped category. Everything above is bounded by that.
