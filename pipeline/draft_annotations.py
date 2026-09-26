"""Produce LLM-DRAFTED annotations for human review. NOT ground truth.

Every label this writes is a draft that a human must check. The file it
produces marks each row `annotator=llm-draft` and `reviewed=no`, and
`evaluate.py` refuses to treat unreviewed rows as gold.

Why this exists: labelling 1,335 calls from a blank sheet is slow. Correcting
a draft is much faster. The cost is that the labels are no longer independent
human judgement, which is why the report must describe the annotation as
LLM-drafted and author-reviewed, and why Cohen's kappa against a second
independent annotator is not available.

## How a draft label is decided

The hard part of the task is deciding which calls exploit the vulnerability.
That was done by reading all 28 traces by hand; the result is the trigger set
below, one entry per case. Everything else follows from four written rules,
applied mechanically so that the draft is consistent and reproducible:

  1. A CREATE is PREPARATORY and essential: deploying the attack contract.
  2. A STATICCALL is PREPARATORY and not essential. It cannot change state, so
     it is rarely the exploit. The exception, flagged for review rather than
     applied silently, is a read whose return value is the thing the victim
     relies on (a manipulated price).
  3. A trigger call, and every non-static call inside its subtree, is TRIGGER
     and essential. The subtree is included because the internal steps of the
     exploited function are not separable from it: the transfer performed by a
     flawed `migrateStake` is part of the same act.
  4. Any other non-static call is PREPARATORY if it runs before the first
     trigger, or between two triggers, and EXTRACTION if it runs after the
     last trigger has finished. Between two triggers counts as preparatory
     because the attack is still under way, not yet being cashed out.

Rows where these rules are least reliable are marked in `notes` so review
effort goes where it is worth spending.

## A confound to be aware of

Rules 1, 2 and 4 are structural, and the C0 baseline in classify.py is also
structural. The two therefore share assumptions, so C0 will agree with this
draft more than it deserves. Any comparison of C0 against these draft labels
is partly circular and must not be reported as C0's accuracy. Once a human
has reviewed the rows, the reviewed labels are independent of C0 to the extent
that the human disagreed with the draft, and only those reviewed rows are
treated as gold.

Usage
    python pipeline/draft_annotations.py            # writes the draft sheet
    python pipeline/draft_annotations.py --stats    # summary only, no write
"""
from __future__ import annotations

import argparse
import csv

import config
import frame_context as fc
from make_annotation_sheet import COLUMNS, build_rows, clip, kappa_subset, write_csv

# ---------------------------------------------------------------------------
# Trigger sets, established by reading each trace.
#
# Default (an empty list here) means: use the frames the benchmark's own
# ground-truth function matches, which `is_gt_vuln_function` already marks.
# For all 28 cases that set was checked against the trace by hand. Two cases
# needed an addition, recorded with the reason:
EXTRA_TRIGGERS: dict[str, list[int]] = {
    # Formation.Fi: the deposit at frame 6 is the price manipulation itself.
    # It shifts the vault's totalTokens within the transaction, which is what
    # makes the swapIn at frame 12 mis-price. Removing it defeats the attack,
    # so by the written test it is a trigger, not setup.
    "C17": [6],
    # MorphoBlue: setAuthorizationWithSig at frame 19 installs the attacker as
    # an authorised manager of the victim's position using a signature. The
    # borrow at frame 22 only succeeds because of it.
    "C18": [19],
}

# Calls known to be artefacts of the attacker's own debugging, left in the
# deployed bytecode. They are not part of the economic exploit.
DEBUG_FUNCTIONS = {"log"}


def subtree_of(rows_by_index: dict[int, dict], roots: set[int]) -> set[int]:
    """Every frame reachable downward from any root, including the roots."""
    out = set(roots)
    changed = True
    while changed:
        changed = False
        for idx, row in rows_by_index.items():
            if idx not in out and row["parent"] in out:
                out.add(idx)
                changed = True
    return out


def draft_case(case_id: str, rows: list[dict], category: str) -> dict[int, dict]:
    by_index = {r["index"]: r for r in rows}
    gt = {r["index"] for r in rows if r["is_gt_vuln_function"]}
    roots = gt | set(EXTRA_TRIGGERS.get(case_id, []))
    trigger_zone = subtree_of(by_index, roots) if roots else set()

    first_trigger = min(trigger_zone) if trigger_zone else None
    last_trigger = max(trigger_zone) if trigger_zone else None

    out: dict[int, dict] = {}
    for row in rows:
        idx = row["index"]
        note = ""

        if row["kind"] == "CREATE":
            role, ess = "PREPARATORY", "yes"
        elif row["kind"] == "STATICCALL":
            role, ess = "PREPARATORY", "no"
            if row["function"].lower() in DEBUG_FUNCTIONS:
                note = "debug log left in the attacker's bytecode, not part of the exploit"
            elif category == "price_oracle_manipulation" and idx in trigger_zone:
                note = ("CHECK: read inside the exploit in a price-manipulation case. "
                        "If the victim relies on this returned value it is a TRIGGER.")
        elif idx in trigger_zone:
            role, ess = "TRIGGER", "yes"
            if idx not in roots:
                note = "internal step of the exploited call"
        elif first_trigger is None:
            role, ess = "PREPARATORY", "yes"
            note = "CHECK: no trigger identified for this case"
        elif idx < first_trigger:
            role, ess = "PREPARATORY", "yes"
        elif idx > last_trigger:
            role, ess = "EXTRACTION", "yes"
        else:
            role, ess = "PREPARATORY", "yes"
            note = ("CHECK: runs between two exploit calls. Preparatory for the next "
                    "one, unless it is already taking profit.")

        out[idx] = {"role": role, "essential": ess, "note": note}

    if len(roots) > 10:
        for idx in roots:
            out[idx]["note"] = (f"repeated exploit call ({len(roots)} occurrences); "
                                f"all are TRIGGER by the repetition rule")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stats", action="store_true", help="print a summary, write nothing")
    args = ap.parse_args()

    cases = fc.load_cases()
    sheet_rows = build_rows(cases, verified_only=False)

    drafts: dict[str, dict[int, dict]] = {}
    for case_id in sorted(cases):
        record = fc.load_record(cases[case_id])
        drafts[case_id] = draft_case(case_id, fc.frame_rows(record),
                                     cases[case_id]["category"])

    flagged = 0
    for row in sheet_rows:
        d = drafts[row["case_id"]][int(row["frame_index"])]
        row["role"] = d["role"]
        row["essential"] = d["essential"]
        row["annotator"] = "llm-draft"
        row["reviewed"] = "no"
        row["notes"] = d["note"]
        if d["note"].startswith("CHECK"):
            flagged += 1

    from collections import Counter
    roles = Counter(r["role"] for r in sheet_rows)
    ess = Counter(r["essential"] for r in sheet_rows)
    print(f"rows drafted        : {len(sheet_rows)}")
    print(f"roles               : {dict(roles)}")
    print(f"essential           : {dict(ess)}")
    print(f"flagged for review  : {flagged}")
    print(f"cases with no trigger: "
          f"{[c for c in drafts if not any(v['role'] == 'TRIGGER' for v in drafts[c].values())]}")

    if args.stats:
        return

    cols = COLUMNS[:]
    if "reviewed" not in cols:
        cols.insert(cols.index("annotator"), "reviewed")

    out_dir = config.DATA_DIR / "annotation"
    path = out_dir / "sheet_draft.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(sheet_rows)
    print(f"\nWritten: {path}")
    print("These are DRAFTS. Set reviewed=yes on a row once you have checked it.")
    print("evaluate.py counts only reviewed=yes rows as gold.")


if __name__ == "__main__":
    main()
