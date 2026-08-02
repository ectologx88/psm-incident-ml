# Data sources, provenance and licence

Every provenance claim in this repo should be checkable by a stranger with a
browser and `curl`. This document is where that promise is kept: each source has
a URL, a retrieval date, the terms text we actually read, and an honest
confidence rating in our reading of it.

**All retrieval dates below are 2026-08-02**, the date this document was
compiled. Every URL in the table was fetched on that date and returned HTTP 200
unless noted otherwise.

> **Not legal advice.** The author is not a lawyer. This document separates two
> different kinds of statement, and the distinction is load-bearing:
> **[VERIFIED]** — text we retrieved and read at the cited URL on the cited date;
> **[INFERENCE]** — our reading of what that text means. Inferences may be wrong.
> Do your own diligence before relying on any of this commercially.

---

## Summary table

| # | Source | URL | What we take from it | Retrieved | Licence basis | Confidence |
|---|---|---|---|---|---|---|
| 1 | BSEE Listing and Status of Incident Investigations | `https://www.data.bsee.gov/Other/DataTables/IncidentInvestigations.aspx` | The incident spine: one row per investigation (date, time, lease, area/block, incident type, panel/district, status) | 2026-08-02 | US Government work; BSEE states site content is public information | **High** |
| 2 | BSEE Incident Investigations field definitions | `https://www.data.bsee.gov/Other/DataTables/FieldDefinitions.aspx?page=incinv` | Column semantics, data types, field lengths | 2026-08-02 | Same as #1 | **High** (licence) / **Low** (completeness — see §2) |
| 3 | BSEE Raw Data hub | `https://www.data.bsee.gov/Main/RawData.aspx` | The bulk ZIP download used by the pipeline (`/Other/Files/IncInvRawData.zip`) | 2026-08-02 | Same as #1 | **High** |
| 4 | BSEE District investigation reports (PDF index) | `https://www.bsee.gov/what-we-do/incident-investigations/offshore-incident-investigations/district-investigation-reports` | Narrative PDFs — causes, findings, recommendations | 2026-08-02 | US Government work, **with third-party carve-out** | **Medium** — see §7 |
| 5 | BSEE Panel investigation reports (PDF index) | `https://www.bsee.gov/what-we-do/incident-investigations/offshore-incident-investigations/panel-investigation-reports` | Major-incident panel reports | 2026-08-02 | US Government work, **with third-party carve-out** | **Medium** — see §7 |
| 6 | Energy Institute PSM Framework, Element 19 | `https://www.energyinst.org/` (see §6) | Target *schema shape only* — element numbering | 2026-08-02 | **Copyrighted, third party. Not redistributed.** | **Low** — terms page unreachable |

Confidence is in **our licence reasoning**, not in data quality. Sources 4–6
are lower because of the third-party-content problem (§7) and, for #6, because
we could not retrieve the terms at all (§6).

---

## The licence position, stated plainly

**[VERIFIED]** BSEE publishes a site-wide disclaimer at
`https://www.bsee.gov/disclaimer` (which redirects to
`https://www.bsee.gov/bsee.gov/privacy-disclaimer`) stating:

> "Information presented on this website is considered public information and may be distributed or copied."

and immediately after:

> "Use of appropriate byline/photo/image credit is requested."

**[VERIFIED]** BSEE nominates that same page as the licence in its own
machine-readable catalogue metadata. The JSON-LD embedded in BSEE's data.gov
entry carries `"license": "https://www.bsee.gov/bsee.gov/privacy-disclaimer"`
with `Access Level: public`
(`https://catalog.data.gov/dataset/bsee-data-center-platform-rig-information`).
This matters: it means the disclaimer is not merely a website footer, it is the
document BSEE itself points to from a field whose sole purpose is declaring a
licence.

**[VERIFIED]** The Department of the Interior states at
`https://www.doi.gov/copyright`:

> "Generally, materials produced by federal agencies are in the public domain and may be reproduced without permission."

**[VERIFIED — a negative result, and an important one]** No page on `bsee.gov`
or `data.bsee.gov` that we checked uses the phrase "public domain", cites
17 U.S.C. § 105, or names any licence (CC0, ODbL, or otherwise). **No explicit
licence statement was located at the BSEE URLs checked as of 2026-08-02.** What
exists is a permission-style disclaimer plus the DOI-level public domain
statement above.

**[INFERENCE]** Works prepared by US Government employees within the scope of
their employment are not subject to US copyright protection (17 U.S.C. § 105).
BSEE is a federal bureau, so its investigation reports and data tables are very
likely US Government works and therefore free of US copyright. The verified
disclaimer language is consistent with this. **But BSEE never says so directly**,
and § 105 has real limits — see §7. We rely on § 105 as our reading, not as
BSEE's assertion.

### What this repo does about it

| Layer | Terms |
|---|---|
| **Code** in this repo | MIT — see `LICENSE`. Ours to license, and we do. |
| **Source data** from BSEE | Carries its own terms, described here. **Not** relicensed by us. MIT does not and cannot cover it. |
| **Derived / synthetic columns** | Marked `syn_` per `CLAUDE.md`. Generated by us, correspond to nothing real, and must never be presented as BSEE data. |

Putting an MIT `LICENSE` file at a repo root does not make the data inside it
MIT. If you redistribute the data, the BSEE terms and the §7 caveats travel with
it, not ours.

We honour BSEE's attribution request throughout: data is credited to the Bureau
of Safety and Environmental Enforcement, US Department of the Interior.

---

## 1. Incident Investigations listing — the spine

`https://www.data.bsee.gov/Other/DataTables/IncidentInvestigations.aspx`

One row per BSEE formal incident investigation. Columns: `DATE_OCCURRED`,
`MILITARY_TIME`, `LEASE_NUMBER`, `AREA_BLOCK`, `ACCIDENT_TYPE`,
`PANEL_DISTRICT`, `STATUS`.

**Row count — a moving target, verified three ways on 2026-08-02.** The live
page reported **2,014 items across 101 pages**. The downloaded raw extract
contained **2,014 data rows** (2,015 lines less one header). And
`data/processed/investigations_index.csv`, produced independently by the ingest
pipeline, carried **2,014 rows** when checked. Three paths agreeing is worth
considerably more than any one of them alone.

The brief for this document quoted "~2,011". That figure is **superseded** by
the three checks above.

This number **grows as BSEE adds investigations** — the portal reported its last
refresh as 2026-08-02 02:00 CST. Treat any count in prose as a dated
observation. **The authority for the current count is the output of
`src/psm/spine.py` and the row count of `data/processed/investigations_index.csv`,
not this document.**

**[VERIFIED]** Coverage limits, stated on the page itself:

> "Only the Panel Investigation Reports published in the MMS number series, which started in 1984, are available."

with district reports available from 2005 onward. The table is therefore **not**
a complete census of offshore incidents — it covers *formal investigations*,
which are a selected subset. Any model trained on it inherits that selection.

---

## 2. Field definitions — and a defect you should know about

`https://www.data.bsee.gov/Other/DataTables/FieldDefinitions.aspx?page=incinv`

Supplies field name, data type, length, and definition.

**[VERIFIED] The page is incomplete, and it is incomplete in the worst possible
place.** It lists seven rows, but `AREA_BLOCK` appears **twice** — the second
occurrence with an empty definition — and **`ACCIDENT_TYPE` has no definition at
all**, despite being present in the raw file header. The duplicate row is almost
certainly a copy-paste error where `ACCIDENT_TYPE` belongs.

Reproduce it with the exact commands in §8 — and match the grid markup rather
than the bare string, or an inline JavaScript block inflates the count.

**[INFERENCE]** This is not a footnote. `ACCIDENT_TYPE` is the single most
semantically important column for mapping incidents onto PSM elements — it is
the field `schema/crosswalk.yaml` leans on hardest. Its controlled vocabulary is
therefore **inferred from observed values in the data**, not read from a
published definition. Anyone who disputes our crosswalk is disputing an
inference we had no authoritative source for, and they are entitled to.

Also noted: `MILITARY_TIME` is declared `VARCHAR2(321)` for what is an `HH:MM`
value. Harmless, but a fair indication of how tightly these definitions are
maintained.

---

## 3. Raw Data hub — the bulk download

`https://www.data.bsee.gov/Main/RawData.aspx`

39 dataset ZIPs in delimited ASCII. Ours is
`https://www.data.bsee.gov/Other/Files/IncInvRawData.zip`, containing
`IncInvRawData/mv_acc_investigations.txt` (CSV, quoted strings, header row).

**[VERIFIED]** BSEE explicitly disclaims support for exactly this artefact:

> "we do not provide support for the downloadable raw data"

> "suggested only for those with advanced knowledge of the data involved"

**[VERIFIED — reproducibility trap]** The ZIP's directory entry carries a stale
`2021-05-13` timestamp while the inner `.txt` was dated `2026-08-02 04:49` when
retrieved. The ZIP is regenerated on BSEE's refresh schedule, so **its SHA256
changes even when the data does not meaningfully differ**. If you need a stable
content identity, hash the inner `.txt`, not the ZIP. `data/manifest.csv` (owned
by the ingest pipeline, not this document) is the authority on recorded hashes.

---

## 4 & 5. Investigation report PDFs — two indexes, two shapes

These carry the narrative content: sequence of events, causes, contributing
factors, recommendations. They are the substance of the ML task.

**[VERIFIED] The two indexes are structurally different, and conflating them
silently produces an incomplete corpus:**

| | District | Panel |
|---|---|---|
| Index page | 576 unique `.pdf` links, direct | **zero** direct `.pdf` links |
| Structure | flat — one fetch yields every URL | per-report landing pages, paginated (3 pages) |
| Crawl | single level | **two levels required** |
| PDF path | `/sites/bsee.gov/files/YYYY-MM/…` | resolved per landing page |
| Archive | separate page, 656 more PDFs, 2003–2013 | "To find reports older than BSEE, go here" |

The panel index says outright: "Please click into each report to find associated
documents." A scraper written for the district page and pointed at the panel
page returns **zero results and no error**. Budget for two collectors.

District archive:
`…/district-investigation-reports/district-investigation-reports-archive`

---

## 6. Energy Institute PSM Framework — target schema

### What we verified, and what we could not

**[VERIFIED]** Element 19 of the EI PSM Framework is **"Incident reporting and
investigation"**. Confirmed from EI's own publication title as indexed on
`energyinst.org`, whose URL slug is EI's own wording. Element 20 ("Audit,
assurance, management review and intervention") follows the same public pattern,
indicating this is EI's convention rather than our reconstruction.

**[VERIFIED]** The framework was published in 2010, organised into 4 focus areas
subdivided into 20 elements. Consistently reported across independent
third-party sources.

**[NOT VERIFIED — and this is the gap that decides the recommendation]**
`https://www.energyinst.org/terms` and every other EI page we tried returned
**HTTP 403** to every automated request on 2026-08-02, including with a full
desktop-browser User-Agent. This is bot protection, not a missing page. **We
never read EI's terms of use.** Search-engine snippets suggest EI reserves all
rights in its published material and forbids reproduction beyond private use
without written permission — which is exactly what one expects from a UK
professional body that sells its publications — but a snippet is not a page we
read, and it is deliberately **not quoted here as if it were.**

### What this repo does — the conservative call

**[INFERENCE]** Short factual labels like element names are weak candidates for
copyright protection, EI publishes them openly as publication titles and course
descriptions, and referencing a published framework by name with attribution is
ordinary practice. That argument is probably right.

But we could not verify EI's terms, and the cost of being careful is close to
zero — the ML task keys on element **number**; names are labelling convenience.
When an argument is probably fine but unverifiable, and the conservative option
is nearly free, take the conservative option.

**Therefore:**

| | Rule |
|---|---|
| `schema/e19_target.yaml` and all machine-readable schema | Refer to elements by **NUMBER only** (e.g. `element_19`). Hand-written; contains only field names and picklist vocabularies needed as targets. |
| Prose and documentation | Element names may appear **with explicit attribution to the Energy Institute**, as here, for the reader's orientation. |
| Never in this repo | The full framework text; the 14 expectations under Element 19; EI guidance documents; workbook structure, formulas, scoring or rollup logic; any substantial reproduction of EI material. |

If EI objects to the named references in prose, the fallback is already
specified and cheap: **drop to numbers-only everywhere.** Nothing downstream
breaks.

### The workbook

`E19 Investigation Report - Rev2.xlsx` is a **workplace document**. It is not in
this repo, has never been in this repo, and must never enter it — including as
a derivative, an extract, a screenshot, or a transcription of its structure.
`schema/e19_target.yaml` is hand-written from scratch for that reason. During
preparation of this document the workbook was **not located, not opened, and not
downloaded**.

We claim no rights in the EI PSM Framework. It is referenced as a target
taxonomy; it is not redistributed.

---

## 7. Known limitations and caveats

### 7.1 § 105 does not cover third-party content — read this one

**[INFERENCE, and the most consequential caveat here.]** 17 U.S.C. § 105 removes
copyright protection from works *prepared by* US Government employees as part of
their official duties. It does **not** launder third-party material that happens
to be embedded inside a federal document. An investigation PDF may contain:

- contractor and consultant reports reproduced as appendices
- operator-supplied photographs, schematics, P&IDs, well diagrams
- equipment vendor manuals, spec sheets, datasheets
- laboratory and third-party expert analyses

**Copyright in that material stays with its original owner.** A federal report
being freely downloadable does not make every image inside it freely reusable.

DOI says as much in its own words **[VERIFIED]**
(`https://www.doi.gov/copyright`):

> "However, not all materials appearing on this web site are in the public domain."

> "Some materials have been donated or obtained from individuals or organizations and may be subject to restrictions on use."

BSEE's data-portal disclaimer reinforces the mechanism **[VERIFIED]**: the
database is derived from documents submitted by "oil companies, other Government
Agencies, and/or the public" — that is precisely how non-federal content enters
a nominally federal dataset.

**Practical guidance.** Extracted *text* and *derived structured fields* are the
low-risk use, and are what this project produces. **Re-publishing extracted
images, diagrams, or verbatim appendix material from investigation PDFs is a
materially different act** and is not covered by anything in this document. If
you plan to do it, check the individual document.

### 7.2 Redactions, PII and CBI — counted, not assumed

**[VERIFIED]** On the current district index, **15 of 576** unique PDFs carry a
redaction marker in the filename. The naming is inconsistent, which matters if
you write a detector:

```
W&T 7Mar2026 GB 783_Redacted.pdf              → underscore, capitalised
GC 584 25-Dec-2024 signed 2010 redacted.pdf   → space, lowercase
MC 127 Anadarko 21-Oct-2023 Redacted.pdf      → space, capitalised
SM 130 04Feb23 Redacted 2010.pdf              → mid-filename
```

A naive `endswith("_Redacted.pdf")` catches roughly a third. Use a
case-insensitive substring match on `redact`.

**[VERIFIED]** On the 2003–2013 archive page, **0 of 656** filenames carry any
redaction marker.

**[INFERENCE]** Two readings of that zero, and filenames alone cannot
distinguish them: either older reports were never redaction-reviewed, or they
were redacted without adopting the naming convention. The first is the more
concerning for a public corpus. **Treat the archive as unverified for PII rather
than as clean.**

**[INFERENCE]** That BSEE redacts at all implies the corpus contains material
warranting removal — personal information about injured workers, and plausibly
operator commercial detail. It says nothing about the 561 unmarked current
documents, which were either reviewed and found clean, or not reviewed. **We do
not know which.** If you surface report text in a public interface, sample it
first. Do not assume a government publication has been scrubbed for your use
case.

### 7.3 Accuracy — BSEE's own warnings

**[VERIFIED]**, from the pages cited in §1 and §3:

> "BSEE provides no warranty, expressed or implied, as to the accuracy, reliability or completeness of furnished data."

> "Some errors may exist in this data and we are constantly working to find and eliminate them."

> "This computer data is not intended as a legal document and should not be constructed as such."

(`constructed` is BSEE's own wording; quoted verbatim, uncorrected, so that
anyone grepping for this string finds it.)

BSEE also recommends acquiring data **directly from a bureau server** rather
than via third parties who may alter it. This repo's `data/raw/` is gitignored
and rebuilt from source URLs precisely so users follow that recommendation
rather than trusting a copy we hand them.

Consequences for modelling, concrete and observed: the source data is dirty and
**stays** dirty (`CLAUDE.md`: one report dates its onsite investigation
`29-JUN-0202`). Anomalies are logged to `data/interim/anomalies.jsonl`, never
silently repaired. A model's error bars include BSEE's data-entry error rate,
which is unquantified and unquantifiable from here.

### 7.4 Coverage gaps and selection bias

- **Formal investigations only.** The table is not a census of offshore
  incidents. Which incidents get formally investigated is a BSEE decision, and
  that decision is a selection mechanism sitting upstream of every model trained
  on this data.
- **Panel reports from 1984 (MMS series), online from 1992; district reports
  from 2005.** Anything earlier is absent, not zero.
- **Not all rows have a PDF.** Some are `Status: active` or otherwise lack a
  published report. Row count ≠ document count.
- **Gulf of Mexico dominant.** Pacific and Alaska regions appear far less often.
  Geographic generalisation is unwarranted.
- **Jurisdictional gaps are real, not parse failures.** Some reports have
  genuinely blank cause fields — e.g. a third-party vessel allision outside BSEE
  jurisdiction. `src_cause_status` distinguishes `absent_legitimate` from
  `parse_failed` for exactly this reason. See `CLAUDE.md`.

### 7.5 Live sources drift

Every URL here is live and mutable. Row counts grow, PDFs are re-uploaded under
new paths (note the `_0` suffixes on several filenames, indicating re-uploads),
and `.zip` archives are regenerated on a schedule. **Retrieval date is part of
the citation, not decoration.** Re-running the pipeline on a different date will
produce a different dataset, and that is expected behaviour, not a bug.

---

## 8. Reproducing our retrieval

Everything below was run on 2026-08-02. A stranger should be able to run the
same commands and reach the same pages.

### Structured data (sources 1–3)

```bash
# The bulk extract the pipeline consumes
curl -L -o IncInvRawData.zip https://www.data.bsee.gov/Other/Files/IncInvRawData.zip
unzip IncInvRawData.zip          # → IncInvRawData/mv_acc_investigations.txt

# Row count (subtract 1 for the header)
wc -l IncInvRawData/mv_acc_investigations.txt
```

In-repo, the supported path is the pipeline itself:

```bash
uv run python -m psm.harvest && uv run python -m psm.fetch && uv run python -m psm.extract
```

`data/raw/` is gitignored; `data/manifest.csv` is committed with a SHA256 per
file so a fresh clone can rebuild byte-identical inputs. See the reproducibility
contract in `CLAUDE.md`. Note the ZIP-hash instability described in §3.

### PDF indexes (sources 4–5)

```bash
BASE=https://www.bsee.gov/what-we-do/incident-investigations/offshore-incident-investigations

# District — flat index, direct PDF links
curl -sL $BASE/district-investigation-reports        | grep -oiE 'href="[^"]+\.pdf"' | sort -u | wc -l
curl -sL $BASE/district-investigation-reports        | grep -oiE 'href="[^"]+redact[^"]*\.pdf"'
curl -sL $BASE/district-investigation-reports/district-investigation-reports-archive | grep -c '\.pdf'

# Panel — expect ZERO direct PDF links; this is the two-level case
curl -sL $BASE/panel-investigation-reports           | grep -c '\.pdf'
```

### Licence and terms pages

```bash
curl -sIL https://www.bsee.gov/disclaimer            # → /bsee.gov/privacy-disclaimer
curl -sL  "https://www.data.bsee.gov/Main/HtmlPage.aspx?page=Disclaimer"
curl -sL  https://www.doi.gov/copyright

# BSEE's own machine-readable licence declaration
curl -sL https://catalog.data.gov/dataset/bsee-data-center-platform-rig-information \
  | grep -o '"license": "[^"]*"'
```

**Note these two, so you do not repeat our wasted effort:**

- `https://www.bsee.gov/disclaimers` (plural) → **404**. The singular
  `/disclaimer` is correct.
- `https://www.energyinst.org/*` → **403** to all automated requests, browser
  User-Agent included. Use an actual browser.

### Verifying the field-definitions defect (§2)

```bash
URL="https://www.data.bsee.gov/Other/DataTables/FieldDefinitions.aspx?page=incinv"

# Field names as rendered in the definitions grid.
# Observed 2026-08-02: "AREA_BLOCK AREA_BLOCK" — the duplicate, and no ACCIDENT_TYPE.
curl -sL "$URL" | grep -o 'FDhyperLink[^>]*><font[^>]*>[A-Z_]*' | sed 's/.*>//'

curl -sL "$URL" | grep -o 'FDhyperLink[^>]*><font[^>]*>AREA_BLOCK'    | wc -l   # 2
curl -sL "$URL" | grep -o 'FDhyperLink[^>]*><font[^>]*>ACCIDENT_TYPE' | wc -l   # 0
```

Match the grid markup, not the bare string: a plain `grep -c 'AREA_BLOCK'` on
this page returns 3, because the name also appears inside an inline JavaScript
control block. That is a counting artefact, not a third table row.

---

## 9. Where the detail lives

`docs/_licence.md` holds the full research log: every URL checked with its HTTP
status, which quotes were confirmed by raw fetch versus discarded as unverified
paraphrase, the dead ends, and the open items still outstanding. If you want to
audit how we reached the positions in this document rather than take them on
trust, start there.

Open items carried forward:

1. Retrieve EI's terms of use through a real browser and record the verbatim
   clause — would upgrade §6 from inferred to verified.
2. Locate a per-dataset data.gov entry for Incident Investigations specifically —
   would tighten the licence chain from portal-wide practice to a declaration
   covering our exact table.
3. Sample redacted against non-redacted PDFs to establish what is actually
   removed — would replace inference in §7.2 with observation.
4. Establish whether 2003–2013 archive reports were redaction-reviewed at all.

---

*Compiled 2026-08-02. Data credited to the Bureau of Safety and Environmental
Enforcement, US Department of the Interior. Corrections welcome — if a claim
here does not survive your own check, that is a bug in this document and we want
to hear about it.*
