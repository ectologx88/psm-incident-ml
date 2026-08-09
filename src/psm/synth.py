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
