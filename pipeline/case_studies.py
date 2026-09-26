"""Build the Chapter 5 case studies from real traces and real predictions.

Writes one markdown file per case containing the facts of the attack, the
labelled call tree, and an honest account of where the model agreed with the
benchmark and where it did not. Nothing is written that is not derived from a
file in data/.

Cases are chosen to cover the interesting shapes rather than to flatter the
system: the largest trace, the deepest, a single-call exploit, and a case the
replay could not verify.

Usage
    python pipeline/case_studies.py                 # the default selection
    python pipeline/case_studies.py --case C16      # one case
    python pipeline/case_studies.py --all
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import config
import frame_context as fc

# Chosen for what each one exposes, noted so the report can say why.
DEFAULT_SELECTION = {
    "C16": "the largest trace in the corpus, 151 calls: can the model find one "
           "flawed call among many?",
    "C24": "the deepest trace, 82 levels, with the exploit repeated 42 times: "
           "does the model apply the repetition rule?",
    "C06": "the smallest trace, 3 calls: a single delegatecall exploit with "
           "nowhere to hide",
    "C27": "a replay the gas check could not verify: what the pipeline does "
           "when it cannot trust its own input",
}


def brief(indices: list[int], limit: int = 8) -> str:
    """Render a frame-index list without flooding the page.

    A reentrancy case can match the same function forty times, and printing
    every index makes the study unreadable.
    """
    if len(indices) <= limit:
        return str(indices)
    head = ", ".join(str(i) for i in indices[:limit])
    return f"[{head}, ... {len(indices) - limit} more]"


def load_predictions() -> dict[str, dict[str, dict]]:
    """condition -> case_id -> record."""
    out: dict[str, dict[str, dict]] = {}
    for path in sorted(glob.glob(str(config.DATA_DIR / "predictions" / "*_run1.json"))):
        records = json.loads(Path(path).read_text(encoding="utf-8"))
        if records:
            out[records[0]["condition"]] = {r["case_id"]: r for r in records}
    return out


def tree_block(rows: list[dict], labels: dict[str, dict], gt: set[int],
               limit: int | None = None) -> str:
    lines = []
    shown = rows if limit is None else rows[:limit]
    for row in shown:
        lab = labels.get(str(row["index"]), {})
        role = lab.get("role", "?")
        mark = {"PREPARATORY": "prep", "TRIGGER": "EXPLOIT", "EXTRACTION": "take"}.get(role, "?")
        star = "*" if lab.get("essential") == "yes" else " "
        flag = "  <-- benchmark's vulnerable function" if row["index"] in gt else ""
        target = row["target_address"] or row["target"]
        short = target if len(target) <= 12 else f"{target[:8]}..{target[-4:]}"
        indent = "  " * row["depth"]
        lines.append(f"{row['index']:>4} {mark:<8}{star} {indent}{short}.{row['function']}(){flag}")
    if limit is not None and len(rows) > limit:
        lines.append(f"     ... {len(rows) - limit} further calls omitted")
    return "\n".join(lines)


def build(case_id: str, case: dict, preds: dict[str, dict], why: str) -> str:
    record = fc.load_record(case)
    rows = fc.frame_rows(record)
    summary = record["summary"]
    gt = {r["index"] for r in rows if r["is_gt_vuln_function"]}
    roles = fc.address_roles(record)

    out = [f"# Case study {case_id}: {case['name']}", ""]
    out.append(f"*Selected because: {why}*")
    out.append("")
    out.append("## The transaction")
    out.append("")
    out.append(f"- Category: `{case['category']}` ({case['split']} split)")
    out.append(f"- Chain: {case['chain']}, block {record['onchain']['block']}")
    out.append(f"- Hash: `{case['tx_hash']}`")
    out.append(f"- Reported loss: {case.get('loss', 'not recorded')}")
    out.append(f"- Gas used on chain: {record['onchain']['receipt_gas_used']}")
    out.append(f"- Replay: **{'verified' if summary['replay_faithful'] else 'NOT VERIFIED'}** "
               f"({summary['fidelity_note']})")
    out.append(f"- Calls: {len(rows)}, max depth {max(r['depth'] for r in rows)}")
    out.append(f"- Benchmark's vulnerable function: `{case['gt_vuln_functions']}`, "
               f"matching {len(gt)} call(s) at {brief(sorted(gt))}")
    out.append("")

    if not summary["replay_faithful"]:
        out.append("> The replayed gas does not equal the on-chain receipt, so this trace is "
                   "not provably the execution that happened. It is kept in the corpus and "
                   "reported, but excluded from the verified set. Any conclusion drawn from "
                   "it carries that caveat.")
        out.append("")

    out.append("## Addresses")
    out.append("")
    for addr, role in sorted(roles.items(), key=lambda kv: kv[1]):
        out.append(f"- `{addr}` — {role}")
    out.append("")

    for cond in sorted(preds):
        rec = preds[cond].get(case_id)
        if not rec:
            continue
        labels = rec["labels"]
        predicted = {int(i) for i, v in labels.items() if v["role"] == "TRIGGER"}
        found = sorted(predicted & gt)
        missed = sorted(gt - predicted)
        counts = {r: sum(1 for v in labels.values() if v["role"] == r) for r in fc.ROLES}

        out.append(f"## Condition {cond}")
        out.append("")
        out.append(f"- Labelled {len(labels)} of {len(rows)} calls "
                   f"in {rec.get('windows', 1)} request(s)")
        out.append(f"- PREPARATORY {counts['PREPARATORY']}, TRIGGER {counts['TRIGGER']}, "
                   f"EXTRACTION {counts['EXTRACTION']}")
        rate = 100 * len(predicted) / len(rows) if rows else 0
        bench = 100 * len(gt) / len(rows) if rows else 0
        out.append(f"- Called {len(predicted)} calls TRIGGER ({rate:.1f}% of the "
                   f"transaction); the benchmark marks {len(gt)} ({bench:.1f}%)")
        if found:
            out.append(f"- **Found** the benchmark's function at {brief(found)}")
        if missed:
            out.append(f"- **Missed** the benchmark's function at {brief(missed)}")
        if len(predicted) > len(gt) * 3 and gt:
            out.append(f"- Over-labelled TRIGGER by roughly "
                       f"{len(predicted) / len(gt):.0f}x, the central weakness this "
                       f"study measures")
        out.append("")
        out.append("```")
        out.append(tree_block(rows, labels, gt, limit=60))
        out.append("```")
        out.append("")

    out.append("## What to take from this case")
    out.append("")
    out.append("<!-- Write the interpretation here. The numbers above are measured; the "
               "reading of them is the author's. -->")
    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    cases = fc.load_cases()
    preds = load_predictions()
    if not preds:
        raise SystemExit("No predictions found. Run pipeline/classify.py first.")

    if args.case:
        selection = {args.case: "selected on the command line"}
    elif args.all:
        selection = {c: "part of the full corpus" for c in sorted(cases)}
    else:
        selection = DEFAULT_SELECTION

    out_dir = config.DATA_DIR / "case_studies"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for case_id, why in selection.items():
        if case_id not in cases:
            print(f"  skipping {case_id}: not in cases.csv")
            continue
        text = build(case_id, cases[case_id], preds, why)
        path = out_dir / f"{case_id}.md"
        path.write_text(text, encoding="utf-8")
        written.append(path.name)
        print(f"  {path.name}  ({len(text)} chars)")

    index = ["# Case studies", "",
             "Generated by `pipeline/case_studies.py` from the traces in "
             "`data/frames/` and the predictions in `data/predictions/`.",
             "Every number is measured; the interpretation sections are for the author.", ""]
    for case_id, why in selection.items():
        if f"{case_id}.md" in written:
            index.append(f"- [{case_id}]({case_id}.md) — {why}")
    (out_dir / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"\nWritten {len(written)} case studies to {out_dir}")


if __name__ == "__main__":
    main()
