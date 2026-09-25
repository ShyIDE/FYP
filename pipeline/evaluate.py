"""Step 7: score the prediction runs.

Two groups of metrics, kept apart on purpose.

Metrics that need no human labels, computable as soon as predictions exist:
  - trigger hit@1 and hit@3 against the benchmark's ground-truth function
  - agreement between repeated runs of the same condition
  - label coverage, malformed-reply counts, tokens consumed

Metrics that need the annotation sheet filled in:
  - accuracy, macro-F1, per-role precision and recall, confusion matrix
  - essential precision and recall
  - Cohen's kappa between the two annotators

If the sheet has no labels, the second group is reported as unavailable rather
than estimated. Nothing here invents a number.

Usage
    python pipeline/evaluate.py
    python pipeline/evaluate.py --verified-only
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
from collections import Counter, defaultdict
from pathlib import Path

import config
import frame_context as fc

ROLES = list(fc.ROLES)


# ---------------------------------------------------------------- loading
def load_runs() -> dict[str, dict[int, list[dict]]]:
    """condition -> run number -> list of case records."""
    out: dict[str, dict[int, list[dict]]] = defaultdict(dict)
    for path in sorted(glob.glob(str(config.DATA_DIR / "predictions" / "*_run*.json"))):
        records = json.loads(Path(path).read_text(encoding="utf-8"))
        if not records:
            continue
        cond = records[0]["condition"]
        run = records[0]["run"]
        out[cond][run] = records
    return out


def load_gold() -> dict[tuple[str, int], dict]:
    """(case_id, frame_index) -> {role, essential} from the annotation sheet."""
    sheet = config.DATA_DIR / "annotation" / "sheet.csv"
    if not sheet.exists():
        return {}
    gold = {}
    with open(sheet, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            role, ess = r["role"].strip().upper(), r["essential"].strip().lower()
            if role and ess:
                gold[(r["case_id"], int(r["frame_index"]))] = {"role": role, "essential": ess}
    return gold


# ------------------------------------------------- metrics without labels
def trigger_hits(records: list[dict], cases: dict) -> dict:
    """Does the model's TRIGGER prediction find the benchmark's function?

    The benchmark names one vulnerable function per case. Predicted TRIGGER
    calls are ranked by execution order, and hit@k asks whether any of the
    first k of them is a call to that function. Execution order is used
    because the model returns labels, not scores, so no better ranking exists.
    """
    hit1 = hit3 = hitany = considered = 0
    for rec in records:
        case = cases[rec["case_id"]]
        record = fc.load_record(case)
        gt_idx = {r["index"] for r in fc.frame_rows(record) if r["is_gt_vuln_function"]}
        if not gt_idx:
            continue
        considered += 1
        predicted = [int(i) for i, v in sorted(rec["labels"].items(), key=lambda kv: int(kv[0]))
                     if v["role"] == "TRIGGER"]
        if predicted[:1] and set(predicted[:1]) & gt_idx:
            hit1 += 1
        if set(predicted[:3]) & gt_idx:
            hit3 += 1
        if set(predicted) & gt_idx:
            hitany += 1
    return {"cases": considered, "hit@1": hit1, "hit@3": hit3, "hit@any": hitany}


def run_agreement(runs: dict[int, list[dict]]) -> dict:
    """How often repeated runs at temperature 0 give the same label."""
    if len(runs) < 2:
        return {}
    per_call: dict[tuple[str, str], list[str]] = defaultdict(list)
    per_ess: dict[tuple[str, str], list[str]] = defaultdict(list)
    for records in runs.values():
        for rec in records:
            for idx, v in rec["labels"].items():
                per_call[(rec["case_id"], idx)].append(v["role"])
                per_ess[(rec["case_id"], idx)].append(v["essential"])
    n = len(runs)
    full = [k for k, v in per_call.items() if len(v) == n]
    same_role = sum(1 for k in full if len(set(per_call[k])) == 1)
    same_ess = sum(1 for k in full if len(set(per_ess[k])) == 1)
    return {
        "runs": n,
        "calls_in_all_runs": len(full),
        "role_identical": same_role,
        "role_identical_pct": round(100 * same_role / len(full), 1) if full else None,
        "essential_identical": same_ess,
        "essential_identical_pct": round(100 * same_ess / len(full), 1) if full else None,
    }


def usage_totals(records: list[dict]) -> dict:
    prompt = sum(r["usage"].get("prompt_tokens", 0) for r in records)
    completion = sum(r["usage"].get("completion_tokens", 0) for r in records)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "requests": sum(r.get("windows", 1) for r in records),
        "seconds": round(sum(r.get("seconds", 0) for r in records), 1),
    }


def coverage(records: list[dict]) -> dict:
    expected = sum(r["n_calls"] for r in records)
    got = sum(len(r["labels"]) for r in records)
    blank_role = sum(1 for r in records for v in r["labels"].values() if not v["role"])
    return {
        "calls": expected,
        "labelled": got,
        "coverage_pct": round(100 * got / expected, 1) if expected else None,
        "blank_role": blank_role,
        "cases_with_problems": sum(1 for r in records if r["problems"]),
    }


# ---------------------------------------------------- metrics with labels
def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def score_against_gold(records: list[dict], gold: dict) -> dict | None:
    pairs = []
    ess_pairs = []
    for rec in records:
        for idx, v in rec["labels"].items():
            key = (rec["case_id"], int(idx))
            if key in gold:
                pairs.append((gold[key]["role"], v["role"]))
                ess_pairs.append((gold[key]["essential"], v["essential"]))
    if not pairs:
        return None

    correct = sum(1 for g, p in pairs if g == p)
    matrix = Counter(pairs)
    per_role, f1s = {}, []
    for role in ROLES:
        tp = sum(1 for g, p in pairs if g == role and p == role)
        fp = sum(1 for g, p in pairs if g != role and p == role)
        fn = sum(1 for g, p in pairs if g == role and p != role)
        p, r, f = prf(tp, fp, fn)
        per_role[role] = {"support": sum(1 for g, _ in pairs if g == role),
                          "precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3)}
        f1s.append(f)

    tp = sum(1 for g, p in ess_pairs if g == "yes" and p == "yes")
    fp = sum(1 for g, p in ess_pairs if g == "no" and p == "yes")
    fn = sum(1 for g, p in ess_pairs if g == "yes" and p == "no")
    ep, er, ef = prf(tp, fp, fn)

    return {
        "scored_calls": len(pairs),
        "accuracy": round(correct / len(pairs), 3),
        "macro_f1": round(sum(f1s) / len(f1s), 3),
        "per_role": per_role,
        "confusion": {f"{g}->{p}": c for (g, p), c in sorted(matrix.items())},
        "essential": {"precision": round(ep, 3), "recall": round(er, 3), "f1": round(ef, 3)},
    }


def cohens_kappa(a: list[str], b: list[str]) -> float | None:
    if not a or len(a) != len(b):
        return None
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum((ca[k] / n) * (cb[k] / n) for k in set(a) | set(b))
    if expected == 1:
        return 1.0
    return round((observed - expected) / (1 - expected), 3)


def annotator_agreement() -> dict | None:
    """Cohen's kappa between the main sheet and the second annotator's copy."""
    first = config.DATA_DIR / "annotation" / "sheet.csv"
    second = config.DATA_DIR / "annotation" / "second_annotator.csv"
    if not (first.exists() and second.exists()):
        return None

    def read(path):
        out = {}
        with open(path, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                role, ess = r["role"].strip().upper(), r["essential"].strip().lower()
                if role and ess:
                    out[(r["case_id"], int(r["frame_index"]))] = (role, ess)
        return out

    a, b = read(first), read(second)
    shared = sorted(set(a) & set(b))
    if not shared:
        return None
    return {
        "overlapping_calls": len(shared),
        "role_kappa": cohens_kappa([a[k][0] for k in shared], [b[k][0] for k in shared]),
        "essential_kappa": cohens_kappa([a[k][1] for k in shared], [b[k][1] for k in shared]),
        "role_raw_agreement": round(
            sum(1 for k in shared if a[k][0] == b[k][0]) / len(shared), 3),
    }


# ---------------------------------------------------------------- report
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verified-only", action="store_true",
                    help="score only cases whose replay matched the receipt")
    args = ap.parse_args()

    cases = fc.load_cases()
    runs = load_runs()
    if not runs:
        raise SystemExit("No predictions found. Run pipeline/classify.py first.")
    gold = load_gold()

    if args.verified_only:
        keep = {c for c in cases if fc.load_record(cases[c])["summary"]["replay_faithful"]}
        for cond in runs:
            for run in runs[cond]:
                runs[cond][run] = [r for r in runs[cond][run] if r["case_id"] in keep]
        print(f"scoring the {len(keep)} verified cases only\n")

    report = {"conditions": {}, "gold_labels_available": len(gold)}

    print(f"{'cond':5}{'runs':>6}{'calls':>8}{'cover%':>8}{'hit@1':>7}{'hit@3':>7}"
          f"{'hitAny':>8}{'tokens':>10}{'acc':>7}{'macroF1':>9}")
    for cond in sorted(runs):
        first = runs[cond][sorted(runs[cond])[0]]
        cov = coverage(first)
        hits = trigger_hits(first, cases)
        use = usage_totals(first)
        scored = score_against_gold(first, gold) if gold else None
        agree = run_agreement(runs[cond])

        report["conditions"][cond] = {
            "coverage": cov, "trigger": hits, "usage": use,
            "run_agreement": agree, "scored": scored,
        }
        acc = f"{scored['accuracy']:.3f}" if scored else "-"
        mf1 = f"{scored['macro_f1']:.3f}" if scored else "-"
        n = hits["cases"] or 1
        print(f"{cond:5}{len(runs[cond]):>6}{cov['calls']:>8}{cov['coverage_pct']:>8}"
              f"{hits['hit@1']}/{n:<5}{hits['hit@3']}/{n:<5}{hits['hit@any']}/{n:<6}"
              f"{use['total_tokens']:>10}{acc:>7}{mf1:>9}")

    kappa = annotator_agreement()
    report["annotator_agreement"] = kappa

    print()
    if gold:
        print(f"Gold labels available for {len(gold)} calls.")
    else:
        print("No gold labels yet: accuracy, macro-F1, per-role precision and recall,")
        print("the confusion matrix and essential P/R cannot be computed. Fill in")
        print("data/annotation/sheet.csv, then re-run this script.")
    if kappa:
        print(f"Annotator agreement over {kappa['overlapping_calls']} calls: "
              f"role kappa {kappa['role_kappa']}, essential kappa {kappa['essential_kappa']}")
    else:
        print("Cohen's kappa unavailable: the second annotator's sheet has no "
              "overlapping labelled rows yet.")

    out = config.DATA_DIR / "predictions" / "metrics.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    main()
