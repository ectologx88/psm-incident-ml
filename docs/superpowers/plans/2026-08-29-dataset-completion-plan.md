# Dataset completion plan — 2026-08-29

Supersedes the sequencing in the earlier remediation plans. Written after the
correction that **there is no template author and no organisation**: this is a
self-contained semi-synthetic dataset built from a public federal corpus, for a
public hackathon.

---

## 1. The goal, stated precisely

> A complete E19 investigation dataset that a stranger can download, open, and
> either **demo the workflow with** or **train a model on** — and in both cases
> tell exactly which cells are real.

Three requirements, and they are not the same:

| | requirement | met by | status |
|---|---|---|---|
| **Complete** | every column carries a value | wiring `synth.py` into the projection | not done, ~1 day |
| **Marked** | every cell's origin is recoverable | the `src`/`xw`/`syn` provenance files | done for `src`/`xw`; `syn` token not yet added |
| **Sound** | the real cells are actually right, and there is enough real signal for the ML tasks to be non-vacuous | everything else in this plan | **the open problem** |

**The single most important thing this plan establishes: wiring synth alone
satisfies "complete".** Every other item here exists to make completeness worth
something. Confusing the two is how a project ships a dense, tested, fully
documented sheet that nobody can use.

---

## 2. Issues, decomposed and sized

### A. Validity — the ledger counts presence, not correctness

**This is a hole in the ledger I built yesterday, and it is the largest issue on
the list.** `psm.ledger` reports a column as filled when its cells are non-empty.
Non-empty is not valid. Measured, on columns the ledger currently calls 100%
real with `gap_policy: none`:

| column | rows | contaminated | how |
|---|---|---|---|
| `Recommendation Description` | 1,244 | **51.8%** | 30.8% carry BSEE form-label text (`RECOMMENDATIONS TO PREVENT RECURRANCE NATURE OF DAMAGE: ... NARRATIVE:`); 31.4% end mid-sentence |
| `Cause Description` | 3,609 | **7.6% unusable**, 28.2% truncated | 2.9% label bleed, 5.0% under five words |

At the source-field level, across 1,219 cleanly-extracted reports:

| field | ends mid-sentence | carries label bleed |
|---|---|---|
| f22 recommendations | 26.9% | **29.5%** |
| f19 contributing cause | 28.5% | 7.1% |
| f18 probable cause | 19.0% | 0.7% |
| f17 findings | 6.7% | 0.1% |

Root cause is the same two-column linearisation problem behind the already-known
P2/P3 items — a terminal anchor with no following anchor swallows whatever
follows it on the page, and wrapped labels detach from their fields.

**Why this outranks everything else:** every downstream method — weak
supervision, clustering, an LLM pass, any classifier — reads this text. Half of
`Recommendation Description` is form furniture. A model trained on it learns to
recognise BSEE's stationery.

### B. Label coverage, and non-random missingness

Cause-label columns, real fraction: `Human Factors Cause` 4.2%, `Risk Management
Cause` 7.6%, `Failed PSM Framework Element` 14.4%, `Cause type` 0%.

Missingness is **not random**. Share of cause statements carrying a mappable
category, by era:

| era | mapped |
|---|---|
| 2000–04 | 0.0% (0/63) |
| 2005–09 | 4.4% (45/1,016) |
| 2010–14 | **0.6%** (5/804) |
| 2015–19 | 7.7% (62/809) |
| 2020–24 | 45.8% (271/592) |
| 2025–29 | 64.2% (138/215) |

Effectively **all labelled data is post-2020**. Consequences:

* A random train/test split leaks era and reports a flattering number that is
  substantially "can you tell what decade this is".
* Any imputation trained on labelled rows is trained on modern structured
  reporting and applied to 2000s free prose.
* The 2010–14 trough at 0.6% is anomalous even against its neighbours and is
  probably a form-revision artifact, not a real change in reporting practice.
  **Unexplained. Worth one hour before any modelling.**

And the task shape is wrong: **48.3% of incidents with a mapped cause carry more
than one distinct category** (mean 3.0 cause statements per incident, max 25).
The schema forces one element per cause.

### C. Structural decisions, cheap now and expensive later

* **C1 — gap-fill policy for the 16 modelling-target columns. UNDECIDED.**
  17,221 cells, 84% of all intra-column gaps. See §4.
* **C2 — synth not wired.** 29 columns, generators written and tested, imported
  by nothing in production. Needs a `syn` token added to the provenance closed
  set and `test_conventions.py` updated.
* **C3 — `--real-only` export not built.** Promised in `ledger.py`'s docstring.
  Until it exists, the dense sheet is the only artifact and the modelling path
  is theoretical.
* **C4 — single-label vs multi-label.** A schema change. Trivial before
  publication, painful after.

### D. Unverified claims and known debt

* **D1** — the crosswalk has never been validated. 22 of 30 gold rows are
  scorable, effective n is 6 decisions (§ adversarial review).
* **D2** — ~37 unexplained missing fatalities (R7).
* **D3** — fields 8–16 collapse into `src_f07_type` on 841 revision-A/B records.
  **No E19 impact** (no E19 column draws on them) but they are the environmental
  covariates any modelling would want.
* **D4** — `e19_schema.py`, `evidence.py`, `fetch.py`, `spine.py` at 0% test
  coverage.

---

## 3. Vetting the data-science methods against the issues

My previous recommendation was to start with embedding + clustering. **That was
wrong, and the contamination measurement above is why** — I proposed it before
measuring how dirty the text is. Every method in this table consumes the same
text, so §A gates all of them.

| method | targets | verdict |
|---|---|---|
| **Weak supervision / label model** | B1 | **Yes, but strictly after A.** The existing rule files already are labelling functions; a label model learns their accuracies without gold labels, which partly dissolves D1, and emits per-cell confidence that fits the provenance design. Run on contaminated text it will learn form furniture as signal. |
| **Embedding + clustering to test the vocabulary** | B1, D1 | **Yes, second.** Tests the crosswalk's central unexamined assumption — that BSEE's six categories partition this text correctly — needs zero labels, one day. But 7.6% of cause statements are unusable and 28.2% truncated; clusters will partly track truncation. Do it on the cleaned text. |
| **Active learning for the gold set** | D1 | **Yes, third.** Sampling where the crosswalk and the label model disagree makes 30 hand labels worth several times 30 hash-sampled ones. Requires the label model to exist first. Highest return per hour of human time on this list. |
| **Multi-label reformulation** | B3 | **Yes, and out of band — do it in Phase 1.** It is a schema decision, not a method, and 48.3% of incidents need it. Cheap now, expensive after entrants have the file. |
| **Model the missingness** | B2 | **Not as remediation — as a published task.** "Is this statement typed?" is near-perfectly predictable from year, so it is useless as a feature and a warning as a finding. But *learning under non-random missingness on a real corpus* is a better hackathon challenge than another text classifier. Zero cost: it is documentation. |
| **TSTR (train synthetic, test real)** | C2 | **Yes, after synth is wired.** Cheap sanity check that the synth layer creates no false structure. Belongs as a test, not an analysis. |
| **Era-stratified splits** | B2 | **Mandatory, not optional, and not really a "method".** Ship the split with the dataset so entrants cannot accidentally leak era. |

**What none of these fix:** completeness. Not one of them puts a value in an
empty cell of `Close out Date`. That is synth's job, and synth is already
written.

---

## 4. The one open decision

**Do the 17,221 gaps inside the 16 modelling-target columns get fabricated?**

Already decided: fill the 37,948 cells in wholly-synthetic columns (uniform
fabrication, nothing confusable with a real fact), and the 3,180 gaps in
ordinary real columns.

The live question is the targets, where `Failed PSM Framework Element` would go
to 86% invented, in the same column and on the same row as real values, for real
named incidents. Options, sized:

1. **Fabricate all** — dense, and the default artifact is mostly fiction in
   exactly the columns entrants would model. Recoverable via `--real-only`.
2. **Fabricate none** — those 16 columns stay 4%–84% and visibly partial; every
   value in them is real or rule-derived; the blank itself carries information.
3. **Split at 50%** — fabricate the nine columns already ≥53% real (3,981
   cells), leave the five worst blank (13,240 cells). Keeps the H&S risk block
   and Incident Type A–C dense while the four cause labels stay honest.

Standing answer is (1). Recorded here because it is the only step in this plan
that is hard to reverse after publication.

---

## 5. Sequence

**Phase 0 — validity. Gates everything.**

0.1 Diagnose the terminal-anchor sink; fix f22 first (29.5% bleed, worst).
0.2 Fix wrapped-label detachment in f19 (7.1%).
0.3 Add a **validity** layer to the ledger, distinct from presence: per column,
    what share of non-empty cells pass a shape check. The current ledger's claim
    that `Recommendation Description` is 100% real is true and misleading.
0.4 Re-run, re-measure, record. Explain the 2010–14 trough.

**Phase 1 — schema decisions, before anything is published.**

1.1 Settle C1 (gap-fill policy).
1.2 Settle C4 (multi-label). If yes, change the causes grain now.
1.3 Build `--real-only` (C3) and ship the era-stratified split alongside it.

**Phase 2 — completeness.**

2.1 Wire `synth.py` into the projection; add `syn` to the provenance closed set;
    update `test_conventions.py` and the `synthetic_column` test in
    `test_ledger.py` (its failure message already says to rewrite rather than
    delete it).
2.2 TSTR as a test.
2.3 Regenerate the ledger. **This is the point at which the goal is met.**

**Phase 3 — soundness, on clean text.**

3.1 Embedding + clustering; test the six-category assumption.
3.2 Weak supervision label model; emit probabilistic labels with confidence.
3.3 Active-learning gold sample; hand-label; report the crosswalk verdict as six
    auditable decisions, not one accuracy number.
3.4 Document the missingness challenge as a hackathon task.

**Deferred, with reasons:** D2 (R7 fatalities — a spine-join question, no E19
impact), D3 (fields 8–16 — ML covariates, no E19 impact), D4 (test coverage on
one-shot generators).

---

## 6. What would make this plan wrong

* If the hackathon is a *workflow demo* only, Phase 3 is unnecessary and Phase 0
  matters much less — nobody reads 3,609 cause statements by hand.
* If it is a *modelling* competition, Phase 2 is nearly unnecessary and could be
  skipped in favour of shipping `--real-only` as the primary artifact.
* The ML target is currently **undecided**, which is why this plan does Phase 0
  and Phase 1 first: they are the steps that pay off under either answer.
