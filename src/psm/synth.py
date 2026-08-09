"""Generate synthetic (syn_) fields for the E19 target schema.

Fills the 28 columns schema/e19_target.yaml's E19 target shape needs that
BSEE never publishes — see docs/superpowers/specs/2026-08-09-synth-fields-
design.md (rev 2) for the design and docs/_synth.md for the plain-language
version. Every rule here is deterministic: int(sha256(report_id + salt), 16)
% N for anything needing variety, and a frozen reference_date (never
date.today()) for anything age-dependent. schema/synth_rules.yaml holds
every threshold — this module must not hardcode one.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
RULES_PATH = REPO / "schema" / "synth_rules.yaml"

REQUIRED_ROW_KEYS = {
    "report_id", "incident_date", "incident_types",
    "property_damage_usd", "area_block",
}


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def validate_row(row: dict[str, Any]) -> None:
    missing = REQUIRED_ROW_KEYS - row.keys()
    if missing:
        raise KeyError(f"row missing required keys: {sorted(missing)}")


def _hash_int(report_id: str, salt: str) -> int:
    return int(hashlib.sha256(f"{report_id}{salt}".encode()).hexdigest(), 16)


def synth_identity_fields(report_id: str, rules: dict[str, Any]) -> dict[str, str]:
    hex_len = rules["identity_token_hex_len"]
    out: dict[str, str] = {}
    for role, salt in rules["identity_salts"].items():
        digest = hashlib.sha256(f"{report_id}{salt}".encode()).hexdigest()
        label = rules["identity_token_labels"][role]
        out[f"{role}_name"] = f"SYN-{label}-{digest[:hex_len]}"
        out[f"{role}_position"] = rules["identity_positions"][role]
    return out


def synth_date_fields(report_id: str, incident_date: date, rules: dict[str, Any]) -> dict[str, date]:
    computed: dict[str, date] = {"incident_date": incident_date}
    for field, spec in rules["date_offsets"].items():
        base = spec["base"]
        if base not in computed:
            raise ValueError(
                f"date_offsets entry {field!r} references base {base!r} which is not "
                "yet computed — check ordering in schema/synth_rules.yaml"
            )
        span = spec["high"] - spec["low"] + 1
        offset = spec["low"] + _hash_int(report_id, spec["salt"]) % span
        computed[field] = computed[base] + timedelta(days=offset)
    del computed["incident_date"]
    return computed


def synth_status_fields(report_id: str, incident_date: date, rules: dict[str, Any]) -> dict[str, str]:
    reference_date = date.fromisoformat(rules["reference_date"])
    age_days = (reference_date - incident_date).days
    thresholds = rules["action_status_age_days"]

    if age_days > thresholds["completed_after"]:
        action_status = "Completed"
    elif age_days > thresholds["in_progress_after"]:
        action_status = "In Progress"
    else:
        action_status = "Pending"

    if action_status == "Completed":
        schedule_status = "N/A"
    else:
        tiebreak = _hash_int(report_id, rules["schedule_status_salt"]) % 2
        schedule_status = "On Schedule" if tiebreak == 0 else "Behind"

    return {"action_status": action_status, "schedule_status": schedule_status}


def synth_severity_fields(
    incident_types: frozenset[str],
    property_damage_usd: float | None,
    rules: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    anomalies: list[dict[str, Any]] = []

    checkbox_tiers = [t for t in rules["severity_tier_order"] if t in rules["severity_tiers"]]
    tier: str | None = None
    for candidate in checkbox_tiers:
        if incident_types & set(rules["severity_tiers"][candidate]):
            tier = candidate
            break
    if tier is None and incident_types:
        tier = "Incident"
    if tier is None:
        anomalies.append({
            "type": "unresolved_incident_classification",
            "note": "incident_types empty or contains no recognised label",
        })

    hs_score = rules["hs_risk_score_by_tier"][tier] if tier else None
    pollution = rules["pollution_label"] in incident_types
    if tier is None:
        env_class, env_score = "Unknown", None
    elif pollution:
        env_class, env_score = tier, hs_score
    else:
        env_class, env_score = "None", 0

    if property_damage_usd is None:
        fin_class, fin_score = "Unknown", None
        anomalies.append({
            "type": "unresolved_property_damage",
            "note": "property_damage_usd is None",
        })
    else:
        fin_class = next(
            t["classification"]
            for t in rules["financial_thresholds_usd"]
            if t["max_usd"] is None or property_damage_usd <= t["max_usd"]
        )
        fin_score = rules["financial_score_by_classification"][fin_class]

    mitigated = (
        max(hs_score - rules["mitigation_delta"], rules["mitigation_floor"])
        if hs_score is not None else None
    )

    fields = {
        "incident_classification": tier or "Unknown",
        "worst_reasonable_outcome": tier or "Unknown",
        "involves_fatality_or_injury": bool(set(rules["fatality_injury_labels"]) & incident_types),
        "hs_risk_score": hs_score,
        "environment_reputation_classification": env_class,
        "environment_reputation_score": env_score,
        "financial_classification": fin_class,
        "financial_score": fin_score,
        "unmitigated_risk_score": hs_score,
        "mitigated_risk_score": mitigated,
    }
    return fields, anomalies


def synth_incident_title(incident_types: frozenset[str], area_block: str, rules: dict[str, Any]) -> str:
    label = ", ".join(sorted(incident_types)) if incident_types else "Unspecified"
    return rules["incident_title_template"].format(incident_type=label, area_block=area_block)


SYN_COLUMN_MANIFEST: dict[str, dict[str, Any]] = {
    "syn_investigation_lead_name": {"description": "Hash-token identity placeholder (SYN-Investigator-<hex6>)", "fabricated": True},
    "syn_investigation_lead_position": {"description": "Fixed placeholder role title", "fabricated": True},
    "syn_incident_classified_by_name": {"description": "Hash-token identity placeholder (SYN-Classifier-<hex6>)", "fabricated": True},
    "syn_incident_classified_by_position": {"description": "Fixed placeholder role title", "fabricated": True},
    "syn_investigation_acceptor_name": {"description": "Hash-token identity placeholder (SYN-Acceptor-<hex6>)", "fabricated": True},
    "syn_investigation_acceptor_position": {"description": "Fixed placeholder role title", "fabricated": True},
    "syn_close_out_approval_name": {"description": "Hash-token identity placeholder (SYN-Approver-<hex6>)", "fabricated": True},
    "syn_close_out_approval_position": {"description": "Fixed placeholder role title", "fabricated": True},
    "syn_responsible_owner_name": {"description": "Hash-token identity placeholder (SYN-Owner-<hex6>)", "fabricated": True},
    "syn_responsible_owner_position": {"description": "Fixed placeholder role title", "fabricated": True},
    "syn_date_of_report": {"description": "incident_date + 5-15 days (deterministic hash offset)", "fabricated": True},
    "syn_approval_date": {"description": "date_of_report + 14-45 days", "fabricated": True},
    "syn_close_out_date": {"description": "approval_date + 30-90 days", "fabricated": True},
    "syn_action_due_date": {"description": "approval_date + 30-180 days", "fabricated": True},
    "syn_agreed_completion_date": {"description": "approval_date + 30-180 days", "fabricated": True},
    "syn_action_status": {"description": "Pending/In Progress/Completed by age vs. frozen reference_date", "fabricated": True},
    "syn_schedule_status": {"description": "On Schedule/Behind/N-A, hash tiebreak unless Completed", "fabricated": True},
    "syn_incident_classification": {"description": "Very Serious/Serious/Incident/Unknown from real incident_types", "fabricated": True},
    "syn_worst_reasonable_outcome": {"description": "Mirrors incident_classification", "fabricated": True},
    "syn_involves_fatality_or_injury": {"description": "Boolean from real incident_types", "fabricated": True},
    "syn_hs_risk_score": {"description": "9/5/2/null encoding of incident_classification", "fabricated": True},
    "syn_environment_reputation_classification": {"description": "Tier name / None / Unknown, gated on Pollution checkbox", "fabricated": True},
    "syn_environment_reputation_score": {"description": "Reuses hs_risk_score value when Pollution set, else 0/null", "fabricated": True},
    "syn_financial_classification": {"description": "Minor/Moderate/Major from real property_damage_usd", "fabricated": True},
    "syn_financial_score": {"description": "2/5/9 encoding of financial_classification", "fabricated": True},
    "syn_unmitigated_risk_score": {"description": "Equals hs_risk_score", "fabricated": True},
    "syn_mitigated_risk_score": {"description": "max(unmitigated - mitigation_delta, mitigation_floor)", "fabricated": True},
    "syn_incident_title": {"description": "Templated from real incident_types + area_block", "fabricated": True},
}


def synthesize_row(row: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    validate_row(row)
    report_id = row["report_id"]

    fields: dict[str, Any] = {}
    fields.update(synth_identity_fields(report_id, rules))
    fields.update(synth_date_fields(report_id, row["incident_date"], rules))
    fields.update(synth_status_fields(report_id, row["incident_date"], rules))
    severity_fields, anomalies = synth_severity_fields(
        row["incident_types"], row["property_damage_usd"], rules
    )
    fields.update(severity_fields)
    fields["incident_title"] = synth_incident_title(row["incident_types"], row["area_block"], rules)

    out = {f"syn_{key}": value for key, value in fields.items()}
    out["anomalies"] = anomalies
    return out
