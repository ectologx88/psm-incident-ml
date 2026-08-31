"""Tests for src/psm/fill.py — deterministic fill of the E19 filled/ layer."""
from __future__ import annotations

import csv  # noqa: F401
from pathlib import Path  # noqa: F401

from psm.fill import (
    element_confidence_by_number,
    element_distribution,
    fill_causes,
    fill_incidents,
    load_rules,
    weighted_pick,
)


def test_weighted_pick_is_deterministic_and_in_vocab():
    weights = {"A": 1, "B": 3, "C": 6}
    first = weighted_pick("INC-1|1", "salt", weights)
    second = weighted_pick("INC-1|1", "salt", weights)
    assert first == second
    assert first in weights


def test_weighted_pick_varies_with_key_and_respects_weights():
    weights = {"A": 1, "B": 3, "C": 6}
    picks = [weighted_pick(f"INC-{i}|1", "salt", weights) for i in range(500)]
    counts = {v: picks.count(v) for v in weights}
    # C (weight 6/10) must dominate A (weight 1/10); loose bounds, no flake.
    assert counts["C"] > counts["A"]
    assert set(picks) == {"A", "B", "C"}


def test_weighted_pick_zero_weight_value_never_chosen():
    weights = {"A": 1, "B": 0}
    assert all(
        weighted_pick(f"k{i}", "s", weights) == "A" for i in range(50)
    )


def test_synth_rules_v2_keys_present():
    rules = load_rules()
    for key in (
        "work_group_weights", "work_group_salt",
        "cause_type_first_cause", "cause_type_weights", "cause_type_salt",
        "likelihood_weights", "er_likelihood_salt", "fin_likelihood_salt",
        "element_fallback_salt",
    ):
        assert key in rules, key
    assert rules["version"] == 2


RULES_FIXTURE = {
    "cause_type_first_cause": "Immediate",
    "cause_type_weights": {"Underlying": 3, "Root": 2},
    "cause_type_salt": "cause_type",
    "element_fallback_salt": "element_fallback",
}


INCIDENT_RULES = {
    "work_group_weights": {"Maintenance": 1, "Drilling": 1},
    "work_group_salt": "work_group",
    "likelihood_weights": {"5": 4, "2": 3, "3": 3},
    "er_likelihood_salt": "er_likelihood",
    "fin_likelihood_salt": "fin_likelihood",
}


def _incident(number, work_group="", er_score="", fin_score=""):
    return {
        "Incident Number": number,
        "Work Group": work_group,
        "Environment & Reputation - Risk Score": er_score,
        "Environment & Reputation - Likelihood": "",
        "Financial Cost & Business Interruption - Risk Score": fin_score,
        "Financial Cost & Business Interruption - Likelihood": "",
    }


def _iprov(number_token="src"):
    return {k: ("" if k != "Incident Number" else number_token)
            for k in _incident("x")}


def _cause(incident, cause, element=""):
    return {
        "Incident Number": incident, "Cause number": cause,
        "Cause Description": "text", "Cause type": "",
        "Risk Management Cause": "", "Human Factors  Cause": "",
        " Failed PSM Framework Element": element,
    }


def _prov(incident_token="src", element_token=""):
    return {
        "Incident Number": incident_token, "Cause number": "src",
        "Cause Description": "src", "Cause type": "",
        "Risk Management Cause": "", "Human Factors  Cause": "",
        " Failed PSM Framework Element": element_token,
    }


def _llm(incident, cause, element, confidence="high"):
    return {
        "incident": incident, "cause": cause,
        "llm_psm_element": element, "llm_confidence": confidence,
    }


def test_fill_causes_keeps_xw_prefers_llm_falls_back_syn():
    causes = [_cause("A", "1", element="15"), _cause("A", "2"), _cause("A", "3")]
    prov = [_prov(element_token="xw"), _prov(), _prov()]
    llm = [
        _llm("A", "1", "8"),      # must NOT overwrite the xw 15
        _llm("A", "2", "17"),
        _llm("A", "3", ""),       # abstained -> syn fallback
    ]
    rows, prov_out, _ = fill_causes(causes, prov, llm, {"15": "high"}, RULES_FIXTURE)

    assert rows[0][" Failed PSM Framework Element"] == "15"
    assert prov_out[0][" Failed PSM Framework Element"] == "xw"
    assert rows[1][" Failed PSM Framework Element"] == "17"
    assert prov_out[1][" Failed PSM Framework Element"] == "llm"
    # fallback drew from the observed llm distribution: {"8": 1, "17": 1}
    assert rows[2][" Failed PSM Framework Element"] in {"8", "17"}
    assert prov_out[2][" Failed PSM Framework Element"] == "syn"
    # every element cell is now non-empty
    assert all(r[" Failed PSM Framework Element"] for r in rows)


def test_fill_causes_confidence_rows():
    causes = [_cause("A", "1", element="15"), _cause("A", "2"), _cause("A", "3")]
    prov = [_prov(element_token="xw"), _prov(), _prov()]
    llm = [_llm("A", "1", "8"), _llm("A", "2", "17", "low"), _llm("A", "3", "")]
    _, _, conf = fill_causes(causes, prov, llm, {"15": "high"}, RULES_FIXTURE)
    by_key = {(c["Incident Number"], c["Cause number"]): c["element_confidence"] for c in conf}
    assert by_key[("A", "1")] == "high"   # crosswalk grade for the xw cell
    assert by_key[("A", "2")] == "low"    # llm_confidence for the llm cell
    assert by_key[("A", "3")] == ""       # syn has no confidence


def test_fill_causes_cause_type_first_is_immediate_rest_weighted():
    causes = [_cause("A", "1"), _cause("A", "2"), _cause("B", "1")]
    prov = [_prov(), _prov(), _prov()]
    llm = [_llm("A", "1", "8"), _llm("A", "2", "8"), _llm("B", "1", "8")]
    rows, prov_out, _ = fill_causes(causes, prov, llm, {}, RULES_FIXTURE)
    assert rows[0]["Cause type"] == "Immediate"
    assert rows[2]["Cause type"] == "Immediate"
    assert rows[1]["Cause type"] in {"Underlying", "Root"}
    assert all(p["Cause type"] == "syn" for p in prov_out)


def test_fill_causes_never_mutates_inputs():
    causes = [_cause("A", "2")]
    prov = [_prov()]
    fill_causes(causes, prov, [_llm("A", "2", "17")], {}, RULES_FIXTURE)
    assert causes[0][" Failed PSM Framework Element"] == ""
    assert prov[0][" Failed PSM Framework Element"] == ""


def test_element_distribution_counts_only_non_empty():
    llm = [_llm("A", "1", "8"), _llm("A", "2", "8"), _llm("A", "3", "")]
    assert element_distribution(llm) == {"8": 2}


def test_element_confidence_by_number_reads_crosswalk(tmp_path):
    cw = tmp_path / "cw.yaml"
    cw.write_text(
        "categories:\n"
        "  Equipment Failure: {primary_element: 15, confidence: high}\n"
        "  Supervision: {primary_element: 17, confidence: low}\n",
        encoding="utf-8",
    )
    assert element_confidence_by_number(cw) == {"15": "high", "17": "low"}


def test_fill_incidents_work_group_everywhere_likelihood_gated_on_score():
    incidents = [
        _incident("A", er_score="5", fin_score="2"),
        _incident("B", er_score="0"),            # zero score -> no ER likelihood
        _incident("C"),                          # empty scores -> no likelihoods
    ]
    prov = [_iprov(), _iprov(), _iprov()]
    rows, prov_out = fill_incidents(incidents, prov, INCIDENT_RULES)

    assert all(r["Work Group"] in {"Maintenance", "Drilling"} for r in rows)
    assert all(p["Work Group"] == "syn" for p in prov_out)

    assert rows[0]["Environment & Reputation - Likelihood"] in {"5", "2", "3"}
    assert prov_out[0]["Environment & Reputation - Likelihood"] == "syn"
    assert rows[0]["Financial Cost & Business Interruption - Likelihood"] in {"5", "2", "3"}

    assert rows[1]["Environment & Reputation - Likelihood"] == ""
    assert rows[2]["Environment & Reputation - Likelihood"] == ""
    assert rows[2]["Financial Cost & Business Interruption - Likelihood"] == ""
    assert prov_out[2]["Environment & Reputation - Likelihood"] == ""


def test_fill_incidents_never_overwrites_existing_work_group():
    incidents = [_incident("A", work_group="Night Crew 7")]
    prov = [_iprov()]
    rows, prov_out = fill_incidents(incidents, prov, INCIDENT_RULES)
    assert rows[0]["Work Group"] == "Night Crew 7"
    assert prov_out[0]["Work Group"] == ""   # untouched -> token unchanged
