"""Apply the author's review of flagged rows back into the drafted sheet.

The 76 rows that draft_annotations.py flagged as uncertain were classified a
second time, with a written reason for each, in
data/annotation/review/check_rows_review.csv. A row becomes ground truth only
when the author has checked it and written `yes` in its `confirm` column. That
is the whole point of this script: it is the one place `reviewed=yes` is set,
and it is set only by the author's confirmation, never by the classification.

To disagree with a classification, edit `your_role` / `your_essential` on that
row before confirming it; the edited value is what gets applied.

Usage
    python pipeline/apply_review.py            # apply confirmed rows
    python pipeline/apply_review.py --dry-run  # show what would change
"""
from __future__ import annotations

import argparse
import csv

import config
import frame_context as fc

REVIEW = config.DATA_DIR / "annotation" / "review" / "check_rows_review.csv"
SHEET = config.DATA_DIR / "annotation" / "sheet_draft.csv"
CONFIRMED = {"yes", "y", "true", "1"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    decisions, problems, pending = {}, [], 0
    with open(REVIEW, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            key = (r["case_id"], r["frame_index"])
            if r["confirm"].strip().lower() not in CONFIRMED:
                pending += 1
                continue
            role = r["your_role"].strip().upper()
            ess = r["your_essential"].strip().lower()
            if role not in fc.ROLES or ess not in fc.ESSENTIAL:
                problems.append(f"{key}: role {role!r} / essential {ess!r} is not valid")
                continue
            if role == "TRIGGER" and ess != "yes":
                problems.append(f"{key}: a TRIGGER must be essential (GUIDELINES.md)")
                continue
            decisions[key] = (role, ess, r.get("decided_by", "").strip())

    if problems:
        print("Not applied, fix these rows first:")
        for p in problems:
            print(f"  {p}")
        raise SystemExit(1)

    with open(SHEET, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames
        rows = list(reader)

    applied = changed = 0
    for r in rows:
        key = (r["case_id"], r["frame_index"])
        if key not in decisions:
            continue
        role, ess, who = decisions[key]
        if (r["role"], r["essential"]) != (role, ess):
            changed += 1
        r["role"], r["essential"], r["reviewed"] = role, ess, "yes"
        # Records how the label was reached, so the report can describe it.
        r["annotator"] = "author" if who == "human" else "claude-then-author"
        applied += 1

    print(f"confirmed and applied : {applied}")
    print(f"  of which changed    : {changed}")
    print(f"not yet confirmed     : {pending}  (left as reviewed=no)")
    if args.dry_run:
        print("dry run: nothing written")
        return
    with open(SHEET, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"written: {SHEET}")


if __name__ == "__main__":
    main()
