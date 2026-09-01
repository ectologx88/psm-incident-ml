"""The exactness test.

The project's stated requirement is that E19 output columns match the source
workbook's field labels exactly. Every mismatch found in review so far came from
a human retyping a label, so this asserts against labels read from
``schema/e19_labels.yaml`` -- which is itself generated from the workbook by
``psm.e19_schema`` -- rather than against anything typed here.

This is the test that would have caught all 23 missing fields and every renamed
column in the earlier hand-built attempt.
"""

from __future__ import annotations

import csv

import pytest

from psm.project import (
    DEFAULT_OUT,
    LABELS_PATH,
    PROJECTION_PATH,
    _iso_date,
    _time,
    label_groups,
    load_yaml,
    pseudonym,
)


@pytest.fixture(scope="module")
def labels() -> dict:
    return load_yaml(LABELS_PATH)


@pytest.fixture(scope="module")
def proj() -> dict:
    return load_yaml(PROJECTION_PATH)


class TestProjectionCoversTheWholeTemplate:
    def test_every_label_is_mapped_or_explicitly_blank(self, labels, proj):
        """No E19 field may be silently absent. Each is a source or a reason code."""
        every = {lab for labs in label_groups(labels).values() for lab in labs}
        mapped = set(proj["mapping"])
        missing = every - mapped
        assert not missing, f"unmapped E19 fields: {sorted(missing)}"

    def test_mapping_invents_no_fields(self, labels, proj):
        every = {lab for labs in label_groups(labels).values() for lab in labs}
        invented = set(proj["mapping"]) - every
        assert not invented, f"mapping names fields the template does not have: {invented}"

    def test_every_entry_has_a_source_or_a_blank_reason(self, proj):
        for lab, spec in proj["mapping"].items():
            assert ("source" in spec) ^ ("blank" in spec), f"{lab!r}: need exactly one"

    def test_blank_reasons_are_from_the_closed_set(self, proj):
        allowed = {"structural", "extractable", "judgement"}
        bad = {lab: s["blank"] for lab, s in proj["mapping"].items()
               if "blank" in s and s["blank"] not in allowed}
        assert not bad, bad

    def test_every_table_group_exists_in_the_template(self, labels, proj):
        known = set(label_groups(labels))
        for table, spec in proj["tables"].items():
            unknown = set(spec["groups"]) - known
            assert not unknown, f"{table}: unknown groups {unknown}"


class TestIrregularLabelsSurviveVerbatim:
    """The template's own typos and whitespace are the real column names."""

    @pytest.mark.parametrize("label", [
        "Incident Classificatioin",
        "incident Title",
        "Human Factors  Cause",
        " Failed PSM Framework Element",
        "What happened?  ",
        "Unmittigated Risk - Score",
        "Mittigated Risk - Score",
        "Health & Safety  - Consequence",
        "Investigation Acceptor/Approver (Owner)- Position",
    ])
    def test_label_present_unnormalised(self, labels, proj, label):
        every = {lab for labs in label_groups(labels).values() for lab in labs}
        assert label in every, "label was normalised during extraction"
        assert label in proj["mapping"], "label was normalised in the projection map"


@pytest.mark.skipif(not (DEFAULT_OUT / "incidents.csv").exists(),
                    reason="run `python -m psm.project` first")
class TestEmittedHeadersMatchTheTemplate:
    """The assertion the whole projection layer exists to satisfy."""

    @pytest.mark.parametrize("table", ["incidents", "causes", "recommendations", "closeout"])
    def test_headers_are_exactly_the_template_labels(self, labels, proj, table):
        with open(DEFAULT_OUT / f"{table}.csv", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        groups = label_groups(labels)
        expected = set(proj["tables"][table].get("foreign_keys", []))
        for g in proj["tables"][table]["groups"]:
            expected |= set(groups[g])
        assert set(header) == expected, (
            f"{table}: extra={set(header) - expected}, missing={expected - set(header)}")

    def test_no_duplicate_columns(self, table="incidents"):
        with open(DEFAULT_OUT / f"{table}.csv", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        assert len(header) == len(set(header))


class TestExtractors:
    def test_iso_date(self):
        assert _iso_date("1. OCCURRED DATE: 06-JUN-2022 TIME: 1030 HOURS") == "2022-06-06"

    def test_iso_date_rejects_bad_month(self):
        assert _iso_date("29-JUN-0202") == "0202-06-29"  # dirty data stays dirty

    def test_iso_date_empty_when_absent(self):
        assert _iso_date("no date here") == ""

    def test_time(self):
        assert _time("DATE: 06-JUN-2022 TIME: 1030 HOURS") == "10:30"

    def test_time_rejects_impossible_hour(self):
        assert _time("TIME: 9999") == ""

    def test_pseudonym_is_stable(self):
        assert pseudonym("David Trocquet", "SUP") == pseudonym("david  trocquet ", "SUP")

    def test_pseudonym_distinguishes_people(self):
        assert pseudonym("David Trocquet", "SUP") != pseudonym("Amy Pellegrin", "SUP")

    def test_pseudonym_empty_stays_empty(self):
        assert pseudonym("   /  ", "SUP") == ""

    def test_pseudonym_carries_prefix(self):
        assert pseudonym("Gerald Taylor", "INV").startswith("INV-")


class TestValuesAreLegal:
    """Header tests are not enough: nothing checked the VALUES.

    BSEE field 28 (MAJOR/MINOR) was mapped as raw text into
    `Incident Classification`, whose picklist is Very Serious Incident / Serious
    Incident / Incident. 234 illegal values shipped, and because verbatim wins
    they suppressed 149 rows that had a valid crosswalked classification. Every
    header test passed throughout.
    """

    @staticmethod
    @pytest.fixture(scope="class")
    def vocab() -> dict:
        labels = load_yaml(LABELS_PATH)
        proj = load_yaml(PROJECTION_PATH)
        by_name = {v["name"]: {str(x) for x in v["values"]}
                   for v in labels.get("vocabularies", []) if v.get("name")}
        exempt = set(proj.get("vocabulary_exempt") or {})
        return {c: by_name[v] for c, v in (proj.get("vocabularies") or {}).items()
                if c not in exempt and v in by_name}

    def test_declared_vocabularies_resolve(self, vocab):
        proj = load_yaml(PROJECTION_PATH)
        exempt = set(proj.get("vocabulary_exempt") or {})
        assert len(vocab) == len({c for c in proj["vocabularies"] if c not in exempt})

    def test_exemptions_are_justified(self):
        """An exemption is a decision. Unexplained, it is a hole in the guard."""
        proj = load_yaml(PROJECTION_PATH)
        for col, why in (proj.get("vocabulary_exempt") or {}).items():
            assert why and len(why) > 20, f"{col}: exemption with no stated reason"

    @pytest.mark.skipif(not (DEFAULT_OUT / "incidents.csv").exists(),
                        reason="run `python -m psm.project` first")
    @pytest.mark.parametrize("table", ["incidents", "causes", "recommendations", "closeout"])
    @pytest.mark.parametrize("subdir", ["", "enriched"])
    def test_no_illegal_values_in_any_committed_table(self, vocab, table, subdir):
        import csv as _csv
        _csv.field_size_limit(10 ** 9)
        path = (DEFAULT_OUT / subdir / f"{table}.csv") if subdir else (DEFAULT_OUT / f"{table}.csv")
        if not path.exists():
            pytest.skip(f"{path.name} not built")
        with path.open(encoding="utf-8", newline="") as fh:
            rows = list(_csv.DictReader(fh))
        if not rows:
            pytest.skip("empty table")
        for col, allowed in vocab.items():
            if col not in rows[0]:
                continue
            bad = [r[col] for r in rows if (r[col] or "").strip() and r[col] not in allowed]
            assert not bad, f"{path.name}:{col!r} has {len(bad)} illegal, e.g. {bad[0]!r}"

    def test_bsee_classification_is_not_mapped_into_the_e19_column(self):
        """The specific defect: two disjoint vocabularies, one column."""
        proj = load_yaml(PROJECTION_PATH)
        for col in ("Incident Classification", "Incident Classificatioin"):
            assert "source" not in proj["mapping"][col], (
                f"{col} must not take a verbatim source -- BSEE field 28 is MAJOR/MINOR")


class TestRecommendationGrain:
    """The declared grain was "one row per recommendation" and the table
    delivered exactly one row per INCIDENT on all 1,079. The splitter used a
    blank line; zero of 1,077 non-empty field-22 values contain one, so it never
    fired once. Nothing noticed, because nothing asserted the grain."""

    def test_nil_returns_are_not_recommendations(self):
        from psm.project import split_recommendations
        for nil in ("None", "N/A", "no", "NIL", "none."):
            assert split_recommendations(nil) == [], f"{nil!r} counted as a recommendation"

    def test_enumerated_items_split(self):
        from psm.project import split_recommendations
        body = "1. Conduct inspections\n2. Survey bulkheads\n3. Verify isolation"
        assert len(split_recommendations(body)) == 3

    @pytest.mark.parametrize("marker", ["1)", "a)", "•"])
    def test_other_enumeration_styles(self, marker):
        from psm.project import split_recommendations
        second = {"1)": "2)", "a)": "b)", "•": "•"}[marker]
        body = f"{marker} first item\n{second} second item"
        assert len(split_recommendations(body)) == 2, body

    def test_a_blank_line_is_not_the_separator(self):
        """Guards the original defect directly: prose split by a blank line is
        still ONE recommendation unless it is enumerated."""
        from psm.project import split_recommendations
        assert len(split_recommendations("first para\n\nsecond para")) == 1

    def test_single_prose_recommendation_stays_one(self):
        from psm.project import split_recommendations
        body = "The district recommends a safety alert be issued to operators."
        assert split_recommendations(body) == [body]

    @pytest.mark.skipif(not (DEFAULT_OUT / "recommendations.csv").exists(),
                        reason="run `python -m psm.project` first")
    def test_shipped_table_has_a_real_grain(self):
        """The check that would have caught it: if every incident has exactly one
        recommendation, the splitter is not working."""
        import csv as _csv
        from collections import Counter
        _csv.field_size_limit(10 ** 9)
        with (DEFAULT_OUT / "recommendations.csv").open(encoding="utf-8", newline="") as fh:
            rows = list(_csv.DictReader(fh))
        per = Counter(r["Incident Number"] for r in rows)
        assert max(per.values()) > 1, "every incident has exactly one recommendation"
        assert len({r["Recommendation Number"] for r in rows}) > 1, \
            "Recommendation Number is constant"
