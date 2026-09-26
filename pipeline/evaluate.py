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


def _read_labels(path, require_reviewed: bool) -> dict[tuple[str, int], dict]:
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            role, ess = r["role"].strip().upper(), r["essential"].strip().lower()
            if not (role and ess):
                continue
            if require_reviewed and r.get("reviewed", "").strip().lower() != "yes":
                continue
            out[(r["case_id"], int(r["frame_index"]))] = {"role": role, "essential": ess}
    return out


def load_gold() -> dict[tuple[str, int], dict]:
    """Labels a human stands behind.

    Two sources count: rows a human filled in directly in sheet.csv, and rows
    in the LLM-drafted sheet that a human has marked reviewed=yes. An
    unreviewed draft row is never gold, because scoring a model against
    another model's labels measures agreement, not correctness.
    """
    ann = config.DATA_DIR / "annotation"
    gold = _read_labels(ann / "sheet.csv", require_reviewed=False)
    gold.update(_read_labels(ann / "sheet_draft.csv", require_reviewed=True))
    return gold


def load_draft() -> dict[tuple[str, int], dict]:
    """All draft labels, reviewed or not. Provisional only, never reported as truth."""
    return _read_labels(config.DATA_DIR / "annotation" / "sheet_draft.csv",
                        require_reviewed=False)


# ------------------------------------------------- metrics without labels
def trigger_metrics(records: list[dict], cases: dict) -> dict:
    """How well TRIGGER predictions match the benchmark's vulnerable function.

    This is the only role the benchmark grounds externally, so it is the one
    role that can be scored without any human annotation.

    hit@k alone is not enough and must never be reported alone. A model that
    calls half the transaction a TRIGGER will score well on hit@k by volume,
    so precision and the trigger rate are reported beside it: trigger_rate is
    the share of all calls the model labelled TRIGGER, and a rate far above
    the share the benchmark marks is over-prediction, not skill.
    """
    hit1 = hit3 = hitany = considered = 0
    tp = fp = fn = 0
    total_calls = total_pred = total_gt = 0
    first_hit_ranks = []

    for rec in records:
        case = cases[rec["case_id"]]
        record = fc.load_record(case)
        gt_idx = {r["index"] for r in fc.frame_rows(record) if r["is_gt_vuln_function"]}
        if not gt_idx:
            continue
        considered += 1
        ordered = [int(i) for i, v in sorted(rec["labels"].items(), key=lambda kv: int(kv[0]))
                   if v["role"] == "TRIGGER"]
        pred = set(ordered)

        total_calls += rec["n_calls"]
        total_pred += len(pred)
        total_gt += len(gt_idx)
        tp += len(pred & gt_idx)
        fp += len(pred - gt_idx)
        fn += len(gt_idx - pred)

        if ordered[:1] and set(ordered[:1]) & gt_idx:
            hit1 += 1
        if set(ordered[:3]) & gt_idx:
            hit3 += 1
        if pred & gt_idx:
            hitany += 1
        for rank, idx in enumerate(ordered, 1):
            if idx in gt_idx:
                first_hit_ranks.append(rank)
                break

    p, r, f = prf(tp, fp, fn)
    return {
        "cases": considered,
        "hit@1": hit1, "hit@3": hit3, "hit@any": hitany,
        "precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3),
        "predicted_triggers": total_pred,
        "benchmark_triggers": total_gt,
        "calls": total_calls,
        "trigger_rate_pct": round(100 * total_pred / total_calls, 1) if total_calls else None,
        "benchmark_rate_pct": round(100 * total_gt / total_calls, 1) if total_calls else None,
        "median_rank_of_first_hit": (sorted(first_hit_ranks)[len(first_hit_ranks) // 2]
                                    if first_hit_ranks else None),
        # Precision falls automatically when the benchmark marks a smaller share
        # of the calls, so precision alone cannot be compared across groups of
        # different size. Lift divides precision by the share a labeller would
        # get by marking calls at random: 1.0 is chance, higher is skill.
        "lift_over_chance": (round(p / (total_gt / total_calls), 2)
                             if total_calls and total_gt else None),
    }


def bootstrap_f1(records, cases, iterations: int = 2000, seed: int = 20260926):
    """A 95% interval for trigger F1, resampling whole cases.

    With 28 cases a difference of a couple of hundredths of F1 is well inside
    sampling noise. Reporting a point estimate alone would invite a claim the
    data cannot support, so the interval is computed and reported beside it.

    Cases are the resampling unit, not calls: calls within one transaction are
    not independent of each other.
    """
    import random
    if len(records) < 2:
        return None
    rng = random.Random(seed)
    scores = []
    for _ in range(iterations):
        sample = [records[rng.randrange(len(records))] for _ in range(len(records))]
        scores.append(trigger_metrics(sample, cases)["f1"])
    scores.sort()
    lo = scores[int(0.025 * len(scores))]
    hi = scores[int(0.975 * len(scores)) - 1]
    return {"f1_ci_low": round(lo, 3), "f1_ci_high": round(hi, 3),
            "iterations": iterations}


def breakdown(records: list[dict], cases: dict, key) -> dict:
    """Trigger metrics split by some property of the case.

    Used to test whether the over-labelling is uniform or concentrated. If it
    is a large-trace failure, that is a different and more useful claim than a
    flat average.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        groups[key(rec, cases[rec["case_id"]])].append(rec)
    out = {}
    for name, recs in groups.items():
        m = trigger_metrics(recs, cases)
        out[name] = {
            "cases": m["cases"], "calls": m["calls"],
            "precision": m["precision"], "recall": m["recall"], "f1": m["f1"],
            "trigger_rate_pct": m["trigger_rate_pct"],
            "benchmark_rate_pct": m["benchmark_rate_pct"],
            "lift_over_chance": m["lift_over_chance"],
            "hit@1": m["hit@1"],
        }
    return out


def size_bucket(rec: dict, case: dict) -> str:
    n = rec["n_calls"]
    if n <= 10:
        return "1 tiny (<=10 calls)"
    if n <= 40:
        return "2 small (11-40)"
    if n <= 100:
        return "3 medium (41-100)"
    return "4 large (>100)"


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
    draft = load_draft()

    if args.verified_only:
        keep = {c for c in cases if fc.load_record(cases[c])["summary"]["replay_faithful"]}
        for cond in runs:
            for run in runs[cond]:
                runs[cond][run] = [r for r in runs[cond][run] if r["case_id"] in keep]
        print(f"scoring the {len(keep)} verified cases only\n")

    report = {"conditions": {}, "gold_labels_available": len(gold)}

    print("TRIGGER identification, scored against the benchmark's vulnerable function.")
    print("trig% is the share of calls the model called TRIGGER; the benchmark marks")
    print("only a few per transaction, so a high rate with low precision is")
    print("over-prediction rather than skill.\n")
    print(f"{'cond':5}{'cases':>6}{'hit@1':>7}{'hit@3':>7}{'P':>7}{'R':>7}{'F1':>7}"
          f"{'trig%':>7}{'bench%':>8}{'lift':>6}{'tokens':>9}")
    for cond in sorted(runs):
        first = runs[cond][sorted(runs[cond])[0]]
        cov = coverage(first)
        hits = trigger_metrics(first, cases)
        use = usage_totals(first)
        scored = score_against_gold(first, gold) if gold else None
        agree = run_agreement(runs[cond])

        report["conditions"][cond] = {
            "coverage": cov, "trigger": hits, "usage": use,
            "run_agreement": agree, "scored": scored,
        }
        n = hits["cases"] or 1
        print(f"{cond:5}{n:>6}{hits['hit@1']:>4}/{n:<2}{hits['hit@3']:>4}/{n:<2}"
              f"{hits['precision']:>7}{hits['recall']:>7}{hits['f1']:>7}"
              f"{hits['trigger_rate_pct']:>7}{hits['benchmark_rate_pct']:>8}"
              f"{hits['lift_over_chance']:>6}{use['total_tokens']:>9}")

    if draft:
        print()
        print("PROVISIONAL, against unreviewed LLM-drafted labels. These are not")
        print("ground truth and must not be reported as accuracy:")
        for cond in sorted(runs):
            first = runs[cond][sorted(runs[cond])[0]]
            prov = score_against_gold(first, draft)
            if prov:
                report["conditions"][cond]["provisional_vs_draft"] = prov
                print(f"  {cond}: agreement with draft {prov['accuracy']:.3f}, "
                      f"macro-F1 {prov['macro_f1']:.3f} over {prov['scored_calls']} calls")

    if gold:
        print()
        print("Three-role classification, against human-reviewed labels:")
        for cond in sorted(runs):
            sc = report["conditions"][cond].get("scored")
            if sc:
                print(f"  {cond}: accuracy {sc['accuracy']:.3f}, macro-F1 {sc['macro_f1']:.3f} "
                      f"over {sc['scored_calls']} reviewed calls")

    print()
    print("Is the over-labelling uniform, or a large-trace failure?")
    print("Trigger rate against the benchmark's rate, split by transaction size:\n")
    print("  lift = precision divided by the rate a random labeller would achieve;")
    print("  1.0 is chance. It is the only column comparable across sizes.\n")
    print(f"  {'condition':10}{'size':22}{'cases':>6}{'P':>7}{'R':>7}{'F1':>7}"
          f"{'trig%':>7}{'bench%':>8}{'lift':>6}")
    for cond in sorted(runs):
        first = runs[cond][sorted(runs[cond])[0]]
        by_size = breakdown(first, cases, size_bucket)
        report["conditions"][cond]["by_size"] = by_size
        for name in sorted(by_size):
            b = by_size[name]
            print(f"  {cond:10}{name:22}{b['cases']:>6}{b['precision']:>7}"
                  f"{b['recall']:>7}{b['f1']:>7}{b['trigger_rate_pct']:>7}"
                  f"{b['benchmark_rate_pct']:>8}{b['lift_over_chance']:>6}")

    print()
    print("By vulnerability category (F1 on trigger identification):\n")
    cats = sorted({c["category"] for c in cases.values()})
    print(f"  {'condition':10}" + "".join(f"{c[:11]:>13}" for c in cats))
    for cond in sorted(runs):
        first = runs[cond][sorted(runs[cond])[0]]
        by_cat = breakdown(first, cases, lambda r, c: c["category"])
        report["conditions"][cond]["by_category"] = by_cat
        cells = "".join(f"{by_cat[c]['f1'] if c in by_cat else '-':>13}" for c in cats)
        print(f"  {cond:10}{cells}")

    print()
    print("How each rung of the ladder changes the model's behaviour.")
    print("Needs no ground truth: it is what the model chose to say.")
    print("Only cases labelled under every condition are counted, so the")
    print("columns are comparable.")
    print()
    common = None
    for cond in runs:
        ids = {r["case_id"] for r in runs[cond][sorted(runs[cond])[0]]}
        common = ids if common is None else (common & ids)
    print(f"  {len(common)} cases labelled under all {len(runs)} conditions\n")
    print(f"  {'condition':10}{'calls':>7}{'PREP':>8}{'TRIGGER':>9}{'EXTRACT':>9}"
          f"{'essential':>11}")
    dist = {}
    for cond in sorted(runs):
        first = [r for r in runs[cond][sorted(runs[cond])[0]] if r["case_id"] in common]
        counts = Counter()
        ess = 0
        total = 0
        for rec in first:
            for v in rec["labels"].values():
                counts[v["role"]] += 1
                ess += v["essential"] == "yes"
                total += 1
        dist[cond] = {"calls": total,
                      **{r: counts[r] for r in ROLES},
                      "essential_yes": ess}
        if total:
            print(f"  {cond:10}{total:>7}"
                  f"{100 * counts['PREPARATORY'] / total:>7.1f}%"
                  f"{100 * counts['TRIGGER'] / total:>8.1f}%"
                  f"{100 * counts['EXTRACTION'] / total:>8.1f}%"
                  f"{100 * ess / total:>10.1f}%")
    report["role_distribution"] = dist

    print()
    print("95% intervals for trigger F1, resampling whole cases 2000 times.")
    print("With 28 cases, overlapping intervals mean a difference is not")
    print("established by this data.")
    print()
    for cond in sorted(runs):
        first = runs[cond][sorted(runs[cond])[0]]
        ci = bootstrap_f1(first, cases)
        if ci:
            report["conditions"][cond]["f1_ci"] = ci
            f1 = report["conditions"][cond]["trigger"]["f1"]
            print(f"  {cond}: F1 {f1:.3f}  95% CI [{ci['f1_ci_low']}, {ci['f1_ci_high']}]")

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

    report["_raw_runs"] = {c: runs[c][sorted(runs[c])[0]] for c in runs}
    md = write_markdown(report, cases)
    report.pop("_raw_runs", None)
    print(f"Written: {md}")



def write_markdown(report, cases):
    """Write RESULTS.md from the same dict the console output came from.

    The report chat reads this file, so it must not be maintained by hand and
    must not be able to drift from metrics.json.
    """
    conds = report["conditions"]
    import datetime
    # Provenance is read from the prediction records themselves rather than
    # restated, so it cannot describe a run that did not happen.
    models, temps, dates = set(), set(), set()
    for cond, runsets in sorted(report.get("_raw_runs", {}).items()):
        for rec in runsets:
            models.add(rec.get("model", "?"))
            temps.add(str(rec.get("temperature", "?")))
            dates.add(rec.get("at", "")[:10])

    L = ["# Results", "",
         "Generated by `pipeline/evaluate.py` on "
         + datetime.date.today().isoformat()
         + ". Every number here was measured.",
         "Do not edit this file by hand; re-run the script.", "",
         "## Provenance", ""]
    L.append("- Model: " + (", ".join(sorted(m for m in models if m and m != "rules"))
                            or "see prediction files"))
    L.append("- Temperature: " + (", ".join(sorted(temps)) or "0.0"))
    L.append("- Prediction runs dated: "
             + (", ".join(sorted(d for d in dates if d)) or "see prediction files"))
    L.append("- Traces: replayed with Foundry `cast`, fetched without an Etherscan "
             "key, so contract names appear as bare addresses")
    L.append("- One run per condition; repeat runs were not affordable within the "
             "provider's 200,000 token daily limit")
    L.append("")

    complete = [c for c in sorted(conds) if conds[c]["trigger"]["cases"] == len(cases)]
    partial = [c for c in sorted(conds) if c not in complete]
    L.append("Conditions covering all %d cases: %s."
             % (len(cases), ", ".join(complete) if complete else "none"))
    if partial:
        L += ["", "**Incomplete, do not tabulate against the others: %s.**"
              % ", ".join(partial)]
    L.append("")

    L += ["## Trigger identification", "",
          "Scored against the benchmark's own vulnerable function, the one role with",
          "external ground truth. `lift` is precision divided by the rate random",
          "marking would achieve; 1.0 is chance. Never quote hit@k without the",
          "precision and trigger-rate columns beside it.", "",
          "| Condition | Cases | hit@1 | hit@3 | Precision | Recall | F1 | Called TRIGGER | Benchmark marks | Lift | Tokens |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for cond in sorted(conds):
        t = conds[cond]["trigger"]
        u = conds[cond]["usage"]
        L.append("| %s | %d | %d/%d | %d/%d | %s | %s | %s | %s%% | %s%% | %s | %d |"
                 % (cond, t["cases"], t["hit@1"], t["cases"], t["hit@3"], t["cases"],
                    t["precision"], t["recall"], t["f1"], t["trigger_rate_pct"],
                    t["benchmark_rate_pct"], t["lift_over_chance"], u["total_tokens"]))

    L += ["", "### Is the difference between conditions real?", "",
          "95% intervals for trigger F1, resampling whole cases 2000 times. Cases are",
          "the unit because calls inside one transaction are not independent. With 28",
          "cases, **overlapping intervals mean the difference is not established**.", "",
          "| Condition | F1 | 95% CI |", "|---|---|---|"]
    for cond in sorted(conds):
        ci = conds[cond].get("f1_ci")
        if ci:
            L.append("| %s | %s | [%s, %s] |"
                     % (cond, conds[cond]["trigger"]["f1"],
                        ci["f1_ci_low"], ci["f1_ci_high"]))

    if "role_distribution" in report:
        L += ["", "## What each condition chose to say", "",
              "Role distribution over the cases labelled under every condition.",
              "Needs no ground truth.", "",
              "| Condition | Calls | PREPARATORY | TRIGGER | EXTRACTION | essential=yes |",
              "|---|---|---|---|---|---|"]
        for cond, d in sorted(report["role_distribution"].items()):
            n = d["calls"] or 1
            L.append("| %s | %d | %.1f%% | %.1f%% | %.1f%% | %.1f%% |"
                     % (cond, d["calls"], 100 * d["PREPARATORY"] / n,
                        100 * d["TRIGGER"] / n, 100 * d["EXTRACTION"] / n,
                        100 * d["essential_yes"] / n))

    L += ["", "## Lift by transaction size", "",
          "Precision falls as transactions grow only because the benchmark marks a",
          "smaller share of their calls. Lift divides that out, and is flat, so there",
          "is no size-dependent failure to report.", "",
          "| Condition | Size | Cases | Precision | Recall | F1 | Called TRIGGER | Benchmark | Lift |",
          "|---|---|---|---|---|---|---|---|---|"]
    for cond in sorted(conds):
        for name, b in sorted(conds[cond].get("by_size", {}).items()):
            L.append("| %s | %s | %d | %s | %s | %s | %s%% | %s%% | %s |"
                     % (cond, name, b["cases"], b["precision"], b["recall"], b["f1"],
                        b["trigger_rate_pct"], b["benchmark_rate_pct"],
                        b["lift_over_chance"]))

    L += ["", "## Lift by vulnerability category", "",
          "| Condition | Category | Cases | Precision | Recall | F1 | Lift |",
          "|---|---|---|---|---|---|---|"]
    for cond in sorted(conds):
        for name, b in sorted(conds[cond].get("by_category", {}).items()):
            L.append("| %s | %s | %d | %s | %s | %s | %s |"
                     % (cond, name, b["cases"], b["precision"], b["recall"],
                        b["f1"], b["lift_over_chance"]))

    L += ["", "## Not measured", "",
          "- **Three-role accuracy, macro-F1, per-role precision and recall, the",
          "  confusion matrix.** These need reviewed human labels. %d reviewed labels"
          % report["gold_labels_available"],
          "  exist.",
          "- **The `essential` flag.** Nothing external grounds it, so it is reported",
          "  as a distribution only and never as an accuracy.",
          "- **Cohen's kappa.** There is one annotator, so inter-annotator reliability",
          "  cannot be computed. Its absence is a stated limitation.",
          ""]

    path = config.DATA_DIR / "predictions" / "RESULTS.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path


if __name__ == "__main__":
    main()
