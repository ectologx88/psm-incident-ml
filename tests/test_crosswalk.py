"""Guards for the crosswalks.

The PSM element crosswalk was keyed to a different numbering than the target
template for its whole life, and nothing caught it: v1 routed Equipment Failure
to element 7 while its own note described "maintenance, inspection and repair
adequacy", which is element 15. Applying it would have put a wrong element on
3,462 cause rows.

These tests exist so that cannot recur silently. The central one asserts every
element number in `crosswalk.yaml` resolves to a real element name in
`e19_labels.yaml`, which is itself generated from the workbook.
"""

from __future__ import annotations

import re

import pytest
import yaml

from psm.project import LABELS_PATH, load_yaml

CROSSWALK_PATH = LABELS_PATH.parent / "crosswalk.yaml"
XW_TYPE_PATH = LABELS_PATH.parent / "xw_incident_type.yaml"


@pytest.fixture(scope="module")
def elements() -> dict[int, str]:
    """{number: name} from the template's own numbered element vocabulary."""
    labels = load_yaml(LABELS_PATH)
    out: dict[int, str] = {}
    for vocab in labels.get("vocabularies", []):
        vals = [str(v) for v in (vocab.get("values") or [])]
        numbered = [v for v in vals if re.match(r"^\d{1,2}\s", v)]
        if len(numbered) == 20:
            for v in numbered:
                out[int(v.split()[0])] = v
            break
    return out


@pytest.fixture(scope="module")
def crosswalk() -> dict:
    return yaml.safe_load(CROSSWALK_PATH.read_text(encoding="utf-8"))


class TestElementNumbersResolve:
    def test_template_has_twenty_numbered_elements(self, elements):
        assert sorted(elements) == list(range(1, 21))

    def test_every_primary_element_exists(self, elements, crosswalk):
        for cat, spec in crosswalk["categories"].items():
            n = spec["primary_element"]
            assert n in elements, f"{cat}: primary_element {n} is not a template element"

    def test_every_secondary_element_exists(self, elements, crosswalk):
        for cat, spec in crosswalk["categories"].items():
            for n in spec.get("also_touches") or []:
                assert n in elements, f"{cat}: also_touches {n} is not a template element"

    def test_primary_is_not_repeated_in_also_touches(self, crosswalk):
        for cat, spec in crosswalk["categories"].items():
            assert spec["primary_element"] not in (spec.get("also_touches") or []), cat


class TestReBasingIsAuditable:
    """v2 must carry its own provenance, or the next reader repeats the mistake."""

    def test_version_is_two_or_later(self, crosswalk):
        assert crosswalk["version"] >= 2

    def test_target_reference_names_the_generated_labels_file(self, crosswalk):
        assert "e19_labels.yaml" in crosswalk["target_element_reference"]

    def test_every_category_records_what_it_was_before(self, crosswalk):
        for cat, spec in crosswalk["categories"].items():
            assert "was_v1" in spec, f"{cat}: no record of the pre-rebasing number"
            assert "matched_on" in spec, f"{cat}: no record of what the element was matched against"

    def test_communication_is_not_element_five(self, elements, crosswalk):
        """The specific trap: element 5 is 'Communication with stakeholders'.

        Matching the BSEE category 'Communication' to it on the word alone would
        route shift-handover failures to external stakeholder communication.
        """
        assert "stakeholder" in elements[5].lower()
        assert crosswalk["categories"]["Communication"]["primary_element"] != 5


class TestAliasesCoverObservedSurfaceForms:
    def test_aliases_resolve_to_real_categories(self, crosswalk):
        cats = set(crosswalk["categories"])
        for surface, target in crosswalk["aliases"].items():
            assert target in cats, f"alias {surface!r} -> unknown category {target!r}"

    def test_alias_keys_are_normalised(self, crosswalk):
        """Lookup is done on case-folded text, so keys must already be folded."""
        for surface in crosswalk["aliases"]:
            assert surface == surface.lower(), f"alias key {surface!r} is not lowercase"

    @pytest.mark.parametrize("surface", ["human error", "management system"])
    def test_the_two_forms_v1_silently_dropped(self, crosswalk, surface):
        """81 typed statements went unmapped on spelling alone under v1."""
        assert surface in crosswalk["aliases"]


class TestIncidentTypeCrosswalk:
    @staticmethod
    @pytest.fixture(scope="class")
    def xw() -> dict:
        return yaml.safe_load(XW_TYPE_PATH.read_text(encoding="utf-8"))

    def test_values_come_from_the_template_picklists(self, xw):
        labels = load_yaml(LABELS_PATH)
        vocab = {v["name"]: set(map(str, v["values"]))
                 for v in labels.get("vocabularies", []) if v.get("name")}
        allowed = {"type_b": vocab.get("B", set()), "type_c": vocab.get("C", set()),
                   "type_d": vocab.get("D", set())}
        for section in ("outcome", "scale", "mechanism"):
            for atom, spec in (xw.get(section) or {}).items():
                for key, permitted in allowed.items():
                    val = spec.get(key)
                    if val and permitted:
                        assert val in permitted, f"{atom}.{key}={val!r} not in the template picklist"

    def test_deliberate_nulls_are_explained(self, xw):
        """A null here is a decision, and must say so or it reads as an omission."""
        for section in ("outcome", "mechanism"):
            for atom, spec in (xw.get(section) or {}).items():
                if any(k in spec and spec[k] is None for k in ("type_c", "type_d")):
                    assert spec.get("note"), f"{atom}: null with no explanation"

    def test_unreachable_values_are_recorded(self, xw):
        assert "Injury Permenant Disability" in xw["unreachable_values"]


class TestCauseQualifiers:
    """Session 3. Matching is by pattern because level 2 is an OPEN vocabulary --
    309 subcategories with free-text drift, not a closed list."""

    @staticmethod
    @pytest.fixture(scope="class")
    def qual() -> dict:
        return yaml.safe_load(
            (LABELS_PATH.parent / "xw_cause_qualifiers.yaml").read_text(encoding="utf-8"))

    def test_all_values_come_from_the_template_picklists(self, qual):
        labels = load_yaml(LABELS_PATH)
        vocab = {v["name"]: set(map(str, v["values"]))
                 for v in labels.get("vocabularies", []) if v.get("name")}
        for section, name in (("risk_management_cause", "Risk Management Cause"),
                              ("human_factors", "Human Factors")):
            permitted = vocab[name]
            for p in qual[section]["patterns"]:
                assert p["value"] in permitted, f"{section}: {p['value']!r} not in {name} picklist"

    def test_cause_type_is_unmapped_with_a_stated_reason(self, qual):
        """Probable/contributing is an axis of primacy; Immediate/Underlying/Root
        is an axis of depth. Not the same axis, so not mapped."""
        assert qual["cause_type"]["policy"] == "leave_unmapped"
        assert "primacy" in qual["cause_type"]["note"].lower()

    def test_every_human_factor_pattern_declares_confidence(self, qual):
        """Half these mappings are attribution, not observation. Unlabelled ones
        would be indistinguishable from the explicit ones in the output."""
        allowed = {"high", "medium", "low"}
        for p in qual["human_factors"]["patterns"]:
            assert p.get("confidence") in allowed, f"{p['match']!r} has no usable confidence"

    def test_human_factors_scoped_to_human_categories(self, qual):
        """Equipment Failure has no person in it to attribute a cognitive mode to."""
        applies = set(qual["human_factors"]["applies_to_categories"])
        assert "Equipment Failure" not in applies
        assert "Human Performance Error" in applies

    def test_sharper_rules_are_listed_before_the_catch_alls(self, qual):
        """First match wins, so 'inadequate' must not precede 'not follow'."""
        matches = [p["match"] for p in qual["risk_management_cause"]["patterns"]]
        assert matches.index("not follow") < matches.index("inadequate")


class TestConsequenceTiers:
    """Session 4. Consequence answers what the event COULD have done.

    Deriving potential from actual under-rates near misses -- measured, not
    asserted: actual-outcome-only leaves 61% of incidents blank with zero at
    consequence D. These guard the method, not the numbers.
    """

    @staticmethod
    @pytest.fixture(scope="class")
    def tiers() -> dict:
        return yaml.safe_load(
            (LABELS_PATH.parent / "xw_consequence_tiers.yaml").read_text(encoding="utf-8"))

    def test_consequence_values_are_template_picklist_values(self, tiers):
        labels = load_yaml(LABELS_PATH)
        allowed = next(set(map(str, v["values"])) for v in labels["vocabularies"]
                       if v.get("name") == "Consequence")
        for src in ("hazard_energy", "actual_outcome_floor"):
            for atom, val in tiers[src].items():
                assert val in allowed, f"{src}.{atom} = {val!r} is not a Consequence value"

    def test_classification_bands_match_the_template(self, tiers):
        """VSI 25-21, SI 20-11, I 10-1 are the template's own, from Monthly Data."""
        labels = load_yaml(LABELS_PATH)
        allowed = next(set(map(str, v["values"])) for v in labels["vocabularies"]
                       if v.get("name") == "Incident Classification")
        assert {b["value"] for b in tiers["classification_bands"]} == allowed
        assert [b["at_least"] for b in tiers["classification_bands"]] == [21, 11, 1]

    def test_likelihood_bands_are_monotonic(self, tiers):
        bands = tiers["likelihood"]["bands"]
        assert [b["at_least"] for b in bands] == sorted(
            (b["at_least"] for b in bands), reverse=True)
        assert [b["likelihood"] for b in bands] == [5, 4, 3, 2, 1]

    def test_observed_rates_resolve_to_their_stated_band(self, tiers):
        """The recorded likelihood must be what the recorded rate actually yields."""
        bands = tiers["likelihood"]["bands"]
        for mech, spec in tiers["likelihood"]["observed_rates"].items():
            got = next(b["likelihood"] for b in bands if spec["rate"] >= b["at_least"])
            assert got == spec["likelihood"], f"{mech}: rate {spec['rate']} -> {got}, not {spec['likelihood']}"

    def test_the_failed_likelihood_approach_is_recorded(self, tiers):
        """Deriving likelihood from actual-vs-potential gap measures realisation,
        not likelihood. It gave 70% of records likelihood 1. Recorded so it is
        not retried."""
        rej = tiers["likelihood"]["rejected_approach"]
        assert "gap" in rej["method"]
        assert "REALISATION" in rej["why"]
        assert "70%" in rej["why"], "the measured failure rate is the point"

    def test_risk_score_declares_it_is_assumed(self, tiers):
        """The template's C x L matrix was not recoverable. Saying so is the point."""
        assert "ASSUMED" in tiers["risk_score"]["assumption"]

    def test_exposure_proxy_records_the_rejected_circular_alternative(self, tiers):
        rej = tiers["exposure_bump"]["rejected_alternative"]
        assert "Evacuation" in rej["signal"]
        assert "circular" in rej["why"].lower()

    def test_financial_bands_ascend(self, tiers):
        unders = [b["under"] for b in tiers["financial_consequence"]["bands"]]
        assert unders[-1] is None
        assert unders[:-1] == sorted(u for u in unders if u is not None)
