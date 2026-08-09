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
