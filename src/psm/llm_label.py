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

Two backends. ``--backend bedrock`` uses boto3 and your AWS credential chain;
``--backend anthropic`` uses ``ANTHROPIC_API_KEY``. ``--dry-run`` writes the
prompt it would send and exits, so it is reviewable without a key and without
spend.

``--pilot`` runs only the statements the crosswalk can also label, which is how
the model choice should be settled: it produces a number instead of an opinion.
There are 524 of them; ``--pilot --limit 60`` is enough to separate two models
and costs under a dollar per model.

Cost, measured from the real prompt (avg 724 input tokens, 3 passes over 3,572
statements = 10,716 calls, 7.75M in / 0.86M out): Haiku 3.5 ~$9.63,
Haiku 4.5 ~$12.04, Sonnet 4.5 ~$36.12. Cost is not the deciding factor at this
scale; label quality is, because these labels drive a schema decision.

Run::

    uv run python -m psm.llm_label --dry-run
    uv run python -m psm.llm_label --backend bedrock --pilot --model <haiku-id>
    uv run python -m psm.llm_label --backend bedrock --model <chosen-id>
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


BEDROCK_DEFAULTS = {
    # Inference-profile IDs. Bedrock model IDs are region-prefixed and change;
    # pass --model explicitly if `aws bedrock list-inference-profiles` disagrees.
    "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
}


def call_bedrock(system: str, user: str, model: str, temperature: float,
                 region: str) -> str:
    """Bedrock Converse. Uses the standard AWS credential chain, so it picks up
    a profile, env vars, SSO or an instance role without this module knowing
    which.

    Retries on throttling with exponential backoff + jitter. A 3,572-statement,
    3-pass run is 10,716 calls with no per-row checkpoint below this function;
    an unhandled throttle near the end of a multi-hour run would discard
    everything before it.
    """
    import random
    import time

    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("bedrock-runtime", region_name=region)
    max_attempts = 8
    for attempt in range(max_attempts):
        try:
            resp = client.converse(
                modelId=model,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": 400, "temperature": temperature},
            )
            return "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            retryable = code in ("ThrottlingException", "TooManyRequestsException",
                                 "ServiceUnavailableException", "ModelTimeoutException")
            if not retryable or attempt == max_attempts - 1:
                raise
            delay = min(60, 2 ** attempt) + random.uniform(0, 1)
            print(f"  [{code}, attempt {attempt + 1}/{max_attempts}, retrying in {delay:.1f}s]",
                 file=sys.stderr)
            time.sleep(delay)
    raise RuntimeError("unreachable")


def call_anthropic(system: str, user: str, model: str, temperature: float) -> str:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=model, max_tokens=400, temperature=temperature,
        system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def write_outputs(out: list[dict], out_dir: Path, suffix: str) -> tuple[Path, list[dict]]:
    """Write both output CSVs. Called at checkpoints during a long run, not
    just once at the end, so a crash loses at most one checkpoint interval
    instead of the whole run."""
    cols = ["incident", "cause", "text", "xw_element", "llm_cause_category",
            "llm_psm_element", "llm_confidence", "llm_passes_agreed", "llm_reason"]
    causes_path = out_dir / f"llm_causes{suffix}.csv"
    with causes_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    # Disagreement queue. Confident disagreements first: an uncertain LLM that
    # differs from the crosswalk says less than a certain one that does.
    order = {"high": 0, "medium": 1, "low": 2}
    dis = [r for r in out if r["xw_element"] and r["llm_psm_element"]
           and r["xw_element"] != r["llm_psm_element"]]
    dis.sort(key=lambda r: order.get(r["llm_confidence"], 3))
    with (out_dir / f"llm_disagreements{suffix}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(dis)
    return causes_path, dis


def main(argv=None) -> int:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", choices=("bedrock", "anthropic"), default="bedrock")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--model", default=None,
                    help="model or inference-profile id; defaults per backend")
    ap.add_argument("--pilot", action="store_true",
                    help="only the statements the crosswalk can also label")
    ap.add_argument("--passes", type=int, default=spec["passes"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=E19)
    args = ap.parse_args(argv)

    if args.model is None:
        args.model = (BEDROCK_DEFAULTS["haiku"] if args.backend == "bedrock"
                      else spec["model_default"])

    elems = elements()
    rows = statements()
    if args.pilot:
        # Deterministic subsample, not the first N: the causes table is ordered
        # by incident, so a head slice would be one era and a handful of
        # operators.
        import hashlib
        rows = sorted((r for r in rows if r["xw_element"]),
                      key=lambda r: hashlib.sha256(
                          f'{r["incident"]}#{r["cause"]}'.encode()).hexdigest())
        print(f"pilot: {len(rows)} statements the crosswalk also labels")
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

    if args.backend == "anthropic" and "ANTHROPIC_API_KEY" not in os.environ:
        print("ANTHROPIC_API_KEY is not set. Use --dry-run to inspect the prompt.",
              file=sys.stderr)
        return 1

    def invoke(s, u):
        if args.backend == "bedrock":
            return call_bedrock(s, u, args.model, spec["temperature"], args.region)
        return call_anthropic(s, u, args.model, spec["temperature"])

    suffix = f"_{args.backend}_pilot" if args.pilot else ""
    checkpoint_every = 200
    out = []
    for i, r in enumerate(rows, 1):
        sysmsg, user = build_prompt(spec, r["text"], elems)
        passes = [parse_response(invoke(sysmsg, user), spec, elems)
                  for _ in range(args.passes)]
        c = consolidate(passes, spec)
        out.append({**r, "llm_cause_category": c["category"],
                    "llm_psm_element": c["element"],
                    "llm_confidence": c["confidence"],
                    "llm_passes_agreed": c["agreed"], "llm_reason": c["reason"]})
        if i % 50 == 0:
            print(f"  {i}/{len(rows)}", file=sys.stderr)
        if i % checkpoint_every == 0:
            write_outputs(out, args.out, suffix)
            print(f"  checkpoint written at {i}/{len(rows)}", file=sys.stderr)

    causes_path, dis = write_outputs(out, args.out, suffix)

    both = [r for r in out if r["xw_element"] and r["llm_psm_element"]]
    agree = len(both) - len(dis)
    print(f"model: {args.model} via {args.backend}")
    print(f"labelled {len(out)} statements -> {causes_path}")
    print(f"  abstained/unparseable : {sum(1 for r in out if not r['llm_psm_element'])}")
    print(f"  confidence            : {dict(Counter(r['llm_confidence'] for r in out))}")
    print(f"  comparable to crosswalk: {len(both)}")
    print(f"  AGREEMENT (not accuracy): {agree}/{len(both)} = "
          f"{100 * agree / len(both):.1f}%" if both else "  no comparable rows")
    print(f"  disagreement queue    -> {args.out / f'llm_disagreements{suffix}.csv'} ({len(dis)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
