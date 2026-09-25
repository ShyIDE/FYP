"""Step 6: build the annotation sheet, the guidelines and the kappa subset.

Writes one row per call frame with the context an annotator needs, leaving
`role` and `essential` empty. Nothing is pre-filled and no label is guessed:
the whole point of the sheet is that a human supplies the ground truth.

Outputs
    data/annotation/sheet.csv             every frame, role and essential blank
    data/annotation/second_annotator.csv  the kappa subset, same columns
    data/annotation/GUIDELINES.md         the written instructions (appendix)

Usage
    python pipeline/make_annotation_sheet.py
    python pipeline/make_annotation_sheet.py --verified-only   # skip the 3 BSC cases
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import config
import frame_context as fc

SEED = 20260925          # fixed so the kappa subset is reproducible
KAPPA_PER_CATEGORY = 1   # one whole transaction per category

COLUMNS = [
    "case_id", "category", "split", "replay_verified", "tx_hash",
    "frame_index", "depth", "parent", "call_tree",
    "kind", "target_address", "target_role", "function", "decoded",
    "value", "gas", "outcome", "args_preview", "events_preview",
    "is_gt_vuln_function",
    "role", "essential", "annotator", "notes",
]


def clip(text, n):
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "..."


def build_rows(cases: dict, verified_only: bool) -> list[dict]:
    out = []
    for case_id in sorted(cases):
        case = cases[case_id]
        record = fc.load_record(case)
        verified = bool(record["summary"]["replay_faithful"])
        if verified_only and not verified:
            continue
        for row in fc.frame_rows(record):
            out.append({
                "case_id": case_id,
                "category": case["category"],
                "split": case["split"],
                "replay_verified": "yes" if verified else "no",
                "tx_hash": case["tx_hash"],
                "frame_index": row["index"],
                "depth": row["depth"],
                "parent": row["parent"] if row["parent"] is not None else "",
                "call_tree": fc.tree_label(row),
                "kind": row["kind"],
                "target_address": row["target_address"] or row["target"],
                "target_role": row["target_role"],
                "function": row["function"],
                "decoded": "yes" if row["decoded"] else "no",
                "value": row["value"] or "",
                "gas": row["gas"],
                "outcome": row["outcome"] or "",
                "args_preview": clip(row["args"], 160),
                "events_preview": clip(row["events"], 160),
                "is_gt_vuln_function": "yes" if row["is_gt_vuln_function"] else "",
                "role": "", "essential": "", "annotator": "", "notes": "",
            })
    return out


def kappa_subset(rows: list[dict], cases: dict) -> list[dict]:
    """One whole transaction per category, chosen with a fixed seed.

    Whole transactions rather than scattered calls: a call's purpose can only
    be judged against the rest of the attack, so an annotator given isolated
    rows would be doing a different, harder task than the first annotator did.
    """
    by_cat: dict[str, list[str]] = {}
    for case_id in {r["case_id"] for r in rows}:
        by_cat.setdefault(cases[case_id]["category"], []).append(case_id)
    rng = random.Random(SEED)
    picked = set()
    for cat in sorted(by_cat):
        picked.update(rng.sample(sorted(by_cat[cat]), min(KAPPA_PER_CATEGORY, len(by_cat[cat]))))
    return [r for r in rows if r["case_id"] in picked]


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


GUIDELINES = """# Annotation guidelines: call role and essentiality

Every call in an attack transaction gets exactly one **role** and one
**essential** flag. Annotate a transaction as a whole, top to bottom, not as
isolated rows: a call's purpose is only visible against the rest of the attack.

## The three roles

Assign the role by asking **what the call contributes to the attack**, not what
the function is named and not who it belongs to.

### PREPARATORY
Sets up the conditions the exploit needs. The attack is not yet happening.
Typical cases:
- taking a flash loan, or borrowing the capital the attack will use
- `approve` calls that let a later transfer move tokens
- deploying a helper contract (`CREATE`)
- reading state to size the attack: `balanceOf`, `getReserves`, price queries
- swaps performed only to acquire the asset the exploit needs

### TRIGGER
Exploits the vulnerability. **The test: if you removed this call and changed
nothing else, would the attack stop working?** If yes, it is a TRIGGER.
Typical cases:
- calling the vulnerable function itself
- the re-entrant call that returns into a victim mid-update
- the call that passes a manipulated price or a forged parameter to the victim
- the unauthorised call that an access-control flaw fails to reject

A transaction usually has few TRIGGER calls. If you have labelled many, check
whether you are labelling the *consequences* of the trigger rather than the
trigger itself.

### EXTRACTION
Realises or secures the profit, after the vulnerability has been exploited.
Typical cases:
- draining a balance, or transferring stolen funds out
- swapping stolen tokens into a stable asset or ETH
- repaying the flash loan
- moving funds to the attacker's own account

## Boundary rules

These exist because they are the cases annotators disagree on.

1. **A flash loan is split.** Taking the loan is PREPARATORY; repaying it is
   EXTRACTION. The repayment is part of realising the profit, because the
   attack only pays out once the loan is settled.
2. **A swap is classified by what it is for.** Acquiring the asset the exploit
   needs is PREPARATORY; converting stolen value is EXTRACTION.
3. **Read-only calls are almost always PREPARATORY.** A `STATICCALL` cannot
   change state, so it can rarely be the trigger. The exception is a read whose
   *return value* is what the victim relies on, for example a manipulated
   price the victim reads; label that TRIGGER.
4. **A `DELEGATECALL` into an implementation keeps the role of the call that
   entered the proxy.** Do not label the proxy hop separately from its purpose.
5. **Repetition does not change the role.** If the same exploit call is made
   forty times in a loop, every one of those calls is a TRIGGER.
6. **Judge by effect, not by name.** A function called `transfer` can be the
   trigger if transferring is what breaks the invariant.

## The essential flag

Separate from the role. Mark `yes` if removing this call would make the attack
fail or lose value; `no` if the attack would still succeed without it.

Calls that are usually **not** essential:
- balance checks the attacker made only to observe or log
- `console.log` calls left in the attacker's contract
- duplicated queries that read the same value twice

A TRIGGER call is essential by definition. A PREPARATORY or EXTRACTION call may
be either. Recording it separately from the role is deliberate: it lets the
experiment ask whether a model can tell a load-bearing setup step from an
incidental one.

## Filling in the sheet

- `role`: one of `PREPARATORY`, `TRIGGER`, `EXTRACTION`. Never blank.
- `essential`: `yes` or `no`. Never blank.
- `annotator`: your initials, so the two annotators can be told apart.
- `notes`: free text. Use it for any row you were unsure about; those rows are
  worth reviewing when the agreement figure is computed.

Columns to your left are context and should not be edited. `target_role` marks
the attacker's account, the attack contract and any contract the benchmark
records as vulnerable. `is_gt_vuln_function` marks the function the benchmark
names as the vulnerability. **It is a hint, not the answer**: the vulnerable
function is usually a TRIGGER, but the benchmark records one function per case
while a transaction often has several trigger calls.

## Agreement

The second annotator labels the transactions in `second_annotator.csv`
independently, without seeing the first annotator's labels, using only these
guidelines. Cohen's kappa is then computed over the overlapping rows, for role
and for essential separately.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verified-only", action="store_true",
                    help="exclude cases whose replay did not match the receipt")
    args = ap.parse_args()

    cases = fc.load_cases()
    rows = build_rows(cases, args.verified_only)
    if not rows:
        raise SystemExit("No frames found. Run pipeline/fetch_traces.py first.")

    out_dir = config.DATA_DIR / "annotation"
    write_csv(out_dir / "sheet.csv", rows)
    subset = kappa_subset(rows, cases)
    write_csv(out_dir / "second_annotator.csv", subset)
    (out_dir / "GUIDELINES.md").write_text(GUIDELINES, encoding="utf-8")

    n_cases = len({r["case_id"] for r in rows})
    n_sub_cases = len({r["case_id"] for r in subset})
    print(f"sheet.csv            : {len(rows)} rows across {n_cases} cases")
    print(f"second_annotator.csv : {len(subset)} rows across {n_sub_cases} cases "
          f"({len(subset) / len(rows) * 100:.1f}% of rows)")
    print(f"  cases: {', '.join(sorted({r['case_id'] for r in subset}))}")
    print(f"GUIDELINES.md        : written")
    print(f"\nAll role/essential cells are empty and must be filled by a human.")


if __name__ == "__main__":
    main()
