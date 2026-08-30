"""LLM cause labelling into `llm_` columns, with a disagreement queue.

The crosswalk maps 524 of 3,572 cause statements. The rest are freetext, and
78% of the corpus predates the vocabulary the crosswalk encodes. This reaches
them.

`llm_` is not `gold_`. An LLM label and a crosswalk rule read the same text by
similar reasoning, so agreement between them measures consensus, not
correctness. CLAUDE.md forbids reporting a metric scored against `llm_`, and
this module does not compute one. What it computes is **agreement**, and a
queue of the rows where the two disagree, which is where an hour of human
attention is worth most.

Outputs, all under `data/processed/e19/`:

``llm_causes.csv``
    ``llm_cause_category``, ``llm_psm_element``, ``llm_confidence``,
    ``llm_reason``, ``llm_passes_agreed``. One row per cause statement.

``llm_disagreements.csv``
    Rows where the LLM and the crosswalk both produced an element and differ.
    Sorted so the confident disagreements come first: an LLM that is uncertain
    and differs is less informative than one that is certain and differs.

Requires ``ANTHROPIC_API_KEY``. ``--dry-run`` writes the prompts it would send
and exits, so the prompt is reviewable without a key and without spend.

Run::

    uv run python -m psm.llm_label --dry-run
    uv run python -m psm.llm_label --limit 100
    uv run python -m psm.llm_label
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
E19 = REPO / "data" / "processed" / "e19"
SPEC = REPO / "schema" / "llm_labelling.yaml"
LABELS = REPO / "schema" / "e19_labels.yaml"


def elements() -> dict[int, str]:
    """The 20 element names, from the template's own vocabulary."""
    lab = yaml.safe_load(LABELS.read_text(encoding="utf-8"))
    for v in lab["vocabularies"]:
        vals = [str(x) for x in (v.get("values") or [])]
        numbered = [x for x in vals if re.match(r"^\d{1,2}\s", x)]
        if len(numbered) == 20:
            return {int(x.split()[0]): x for x in numbered}
    raise RuntimeError("could not locate the 20-element vocabulary")


def statements() -> list[dict]:
    csv.field_size_limit(10 ** 9)
    with (E19 / "enriched" / "causes.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    col = next(c for c in rows[0] if "Failed PSM" in c)
    return [{"incident": r["Incident Number"], "cause": r["Cause number"],
             "text": " ".join((r["Cause Description"] or "").split()),
             "xw_element": (r[col] or "").strip()} for r in rows]


def build_prompt(spec: dict, text: str, elems: dict[int, str]) -> tuple[str, str]:
    body = text[: int(spec["max_chars"])]
    user = spec["user_template"].format(
        statement=body,
        categories=" | ".join(spec["cause_categories"]),
        elements="\n".join(f"  {n}. {name.split(' ', 1)[1]}"
                           for n, name in sorted(elems.items())),
    )
    return spec["system"], user


def parse_response(raw: str, spec: dict, elems: dict[int, str]) -> dict | None:
    """Strict. A response outside the closed vocabularies is DISCARDED.

    Coercing a near-miss ("Human Error" -> "Human Performance Error", element
    "3-ish" -> 3) would quietly manufacture agreement with the crosswalk, which
    is the one number this module reports.
    """
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    cat = obj.get("category")
    if cat == spec["abstain_token"]:
        return {"category": cat, "element": None, "reason": obj.get("reason", "")}
    if cat not in spec["cause_categories"]:
        return None
    el = obj.get("element")
    if not isinstance(el, int) or el not in elems:
        return None
    return {"category": cat, "element": el, "reason": str(obj.get("reason", ""))[:300]}


def consolidate(results: list[dict | None], spec: dict) -> dict:
    """Self-consistency across passes. Confidence is agreement, not the model's
    own stated certainty, which is not calibrated."""
    good = [r for r in results if r]
    if not good:
        return {"category": "", "element": "", "confidence": "low",
                "reason": "no parseable response", "agreed": 0}
    els = [r["element"] for r in good]
    top, n = Counter(els).most_common(1)[0]
    if any(e is None for e in els) or n <= len(results) // 2:
        conf = "low"
    elif n == len(results):
        conf = "high"
    else:
        conf = "medium"
    pick = next(r for r in good if r["element"] == top)
    return {"category": pick["category"], "element": "" if top is None else str(top),
            "confidence": conf, "reason": pick["reason"], "agreed": n}


def call(system: str, user: str, model: str, temperature: float) -> str:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=model, max_tokens=400, temperature=temperature,
        system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def main(argv=None) -> int:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=spec["model_default"])
    ap.add_argument("--passes", type=int, default=spec["passes"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=E19)
    args = ap.parse_args(argv)

    elems = elements()
    rows = statements()
    if args.limit:
        rows = rows[: args.limit]

    if args.dry_run:
        sysmsg, user = build_prompt(spec, rows[0]["text"], elems)
        path = args.out / "llm_prompt_example.txt"
        path.write_text(f"MODEL: {args.model}\nPASSES: {args.passes}\n"
                        f"TEMPERATURE: {spec['temperature']}\n\n"
                        f"=== SYSTEM ===\n{sysmsg}\n\n=== USER ===\n{user}\n",
                        encoding="utf-8")
        print(f"dry run. {len(rows)} statements would be labelled, "
              f"{args.passes} passes each = {len(rows) * args.passes} calls.")
        print(f"prompt written to {path}")
        return 0

    if "ANTHROPIC_API_KEY" not in os.environ:
        print("ANTHROPIC_API_KEY is not set. Use --dry-run to inspect the prompt.",
              file=sys.stderr)
        return 1

    out = []
    for i, r in enumerate(rows, 1):
        sysmsg, user = build_prompt(spec, r["text"], elems)
        passes = [parse_response(call(sysmsg, user, args.model, spec["temperature"]),
                                 spec, elems) for _ in range(args.passes)]
        c = consolidate(passes, spec)
        out.append({**r, "llm_cause_category": c["category"],
                    "llm_psm_element": c["element"],
                    "llm_confidence": c["confidence"],
                    "llm_passes_agreed": c["agreed"], "llm_reason": c["reason"]})
        if i % 50 == 0:
            print(f"  {i}/{len(rows)}", file=sys.stderr)

    cols = ["incident", "cause", "text", "xw_element", "llm_cause_category",
            "llm_psm_element", "llm_confidence", "llm_passes_agreed", "llm_reason"]
    with (args.out / "llm_causes.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    # Disagreement queue. Confident disagreements first: an uncertain LLM that
    # differs from the crosswalk says less than a certain one that does.
    order = {"high": 0, "medium": 1, "low": 2}
    dis = [r for r in out if r["xw_element"] and r["llm_psm_element"]
           and r["xw_element"] != r["llm_psm_element"]]
    dis.sort(key=lambda r: order.get(r["llm_confidence"], 3))
    with (args.out / "llm_disagreements.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(dis)

    both = [r for r in out if r["xw_element"] and r["llm_psm_element"]]
    agree = len(both) - len(dis)
    print(f"labelled {len(out)} statements -> {args.out / 'llm_causes.csv'}")
    print(f"  abstained/unparseable : {sum(1 for r in out if not r['llm_psm_element'])}")
    print(f"  confidence            : {dict(Counter(r['llm_confidence'] for r in out))}")
    print(f"  comparable to crosswalk: {len(both)}")
    print(f"  AGREEMENT (not accuracy): {agree}/{len(both)} = "
          f"{100 * agree / len(both):.1f}%" if both else "  no comparable rows")
    print(f"  disagreement queue    -> {args.out / 'llm_disagreements.csv'} ({len(dis)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
