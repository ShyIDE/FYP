"""The tool: give it a transaction, get back what every call in it was for.

This is the deliverable the rest of the pipeline exists to support. It takes a
transaction hash, replays it, parses the call tree, asks the model to label
each call, and prints the attack as a narrative: what set the attack up, what
exploited the flaw, and what took the money out.

It works on any transaction on a supported chain, not only the 28 benchmark
cases, so it can be pointed at a fresh incident.

    python pipeline/analyse.py 0xc310a0af...b6111d
    python pipeline/analyse.py 0x24a68d2a...acdb --chain bsc
    python pipeline/analyse.py 0xaaa... 0xbbb... 0xccc...
    python pipeline/analyse.py incidents.txt --json out.json

Several transactions can be given at once, or a file with one hash per line
(blank lines and lines starting with # are skipped). A transaction that fails
is reported and the rest still run.

What it does NOT do: tell you the transaction is an attack. It assumes you
already believe that and are asking what happened inside it. Nor does it
identify the vulnerability class; it labels the role each call plays.

Accuracy caveat, stated because the tool prints confident-looking output:
measured against the benchmark's own ground truth, the model over-labels
TRIGGER by a wide margin. Treat the TRIGGER set as a shortlist to read, not a
verdict. See STATUS.md for the measured numbers.
"""
from __future__ import annotations

import argparse
import json
import sys

import config
import frame_context as fc
import classify
from fetch_traces import find_cast, onchain_facts, run_cast, fidelity
from trace_parser import parse_trace

ROLE_MARK = {"PREPARATORY": "prep ", "TRIGGER": "EXPLOIT", "EXTRACTION": "take "}


def analyse_transaction(tx_hash: str, chain: str, condition: str) -> dict:
    """Replay, parse and label one transaction. Raises rather than guessing."""
    tx_hash = tx_hash.strip().lower()
    if not (tx_hash.startswith("0x") and len(tx_hash) == 66):
        # Raised, not exited: in a batch one malformed hash must not discard
        # the analyses that already succeeded.
        raise ValueError(
            f"{tx_hash!r} is not a transaction hash (expected 0x + 64 hex digits)")

    url = config.rpc_url(chain)
    cast = find_cast()

    print(f"Transaction {tx_hash[:12]}... on {chain}")
    facts = onchain_facts(url, tx_hash)
    print(f"  block {facts['block']}, {facts['receipt_status']}, "
          f"gas {facts['receipt_gas_used']}")

    mode, raw = "quick", run_cast(cast, tx_hash, url, quick=True)
    parsed = parse_trace(raw)
    ok, note = fidelity(parsed, facts)
    if not ok:
        print(f"  quick replay diverged ({note}); replaying the whole block...")
        mode, raw = "full", run_cast(cast, tx_hash, url, quick=False)
        parsed = parse_trace(raw)
        ok, note = fidelity(parsed, facts)
    print(f"  replay ({mode}): {'verified' if ok else 'NOT VERIFIED'} - {note}")

    # A synthetic case record, so frame_context sees the same shape it does for
    # a benchmark case. There is no ground truth for an arbitrary transaction,
    # so the ground-truth fields are empty rather than invented.
    record = {
        "case": {"case_id": "adhoc", "name": tx_hash[:12], "category": "unknown",
                 "split": "adhoc", "chain": chain, "tx_hash": tx_hash,
                 "gt_vuln_contracts": "", "gt_vuln_functions": ""},
        "onchain": facts,
        "summary": {"replay_faithful": ok, "fidelity_note": note},
        "frames": parsed["frames"],
    }
    rows = fc.frame_rows(record)
    print(f"  {len(rows)} calls, max depth {max(r['depth'] for r in rows)}")

    chunks = classify.chunk_rows(rows, condition)
    print(f"  labelling in {len(chunks)} request(s) with {classify.MODEL}...")
    examples = classify.load_fewshot(condition)
    labels, problems = {}, []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    for chunk in chunks:
        prompt = classify.build_prompt(record, condition, examples, {},
                                       window=chunk, total=len(rows))
        reply = classify.call_groq(prompt)
        text = reply["choices"][0]["message"]["content"]
        for k in usage:
            usage[k] += reply.get("usage", {}).get(k, 0)
        part, probs = classify.parse_labels(text, {r["index"] for r in chunk})
        labels.update(part)
        problems.extend(probs)

    return {"tx_hash": tx_hash, "chain": chain, "condition": condition,
            "model": classify.MODEL, "onchain": facts,
            "replay_verified": ok, "fidelity_note": note,
            "rows": rows, "labels": {str(k): v for k, v in sorted(labels.items())},
            "problems": problems, "usage": usage}


def print_report(result: dict) -> None:
    rows = result["rows"]
    labels = result["labels"]
    by_role: dict[str, list[dict]] = {r: [] for r in fc.ROLES}

    print("\n" + "=" * 72)
    print("CALL-BY-CALL ANALYSIS")
    print("=" * 72)
    for row in rows:
        lab = labels.get(str(row["index"]), {})
        role = lab.get("role", "")
        ess = lab.get("essential", "")
        if role in by_role:
            by_role[role].append(row)
        mark = ROLE_MARK.get(role, "  ?  ")
        star = "*" if ess == "yes" else " "
        target = row["target_address"] or row["target"]
        short = target if len(target) <= 12 else f"{target[:8]}..{target[-4:]}"
        indent = "  " * row["depth"]
        print(f"{row['index']:>4} {mark}{star} {indent}{short}.{row['function']}()")

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  calls labelled : {len(labels)}/{len(rows)}")
    for role in fc.ROLES:
        print(f"  {role:<12}: {len(by_role[role])}")
    print(f"  * marks calls the model judged essential to the attack")

    trig = by_role["TRIGGER"]
    if trig:
        print(f"\n  Calls the model flagged as exploiting the vulnerability "
              f"({len(trig)} of {len(rows)}):")
        for row in trig[:12]:
            target = row["target_address"] or row["target"]
            print(f"    frame {row['index']:>4}  {target}.{row['function']}()")
        if len(trig) > 12:
            print(f"    ... and {len(trig) - 12} more")
        print("\n  Read these first. The model over-labels this role, so treat the")
        print("  list as a shortlist to check, not a conclusion.")

    if not result["replay_verified"]:
        print(f"\n  WARNING: the replay did not match the on-chain receipt "
              f"({result['fidelity_note']}).")
        print("  The trace may not be what actually executed. Do not rely on it.")
    if result["problems"]:
        print(f"\n  {len(result['problems'])} labelling problem(s):")
        for prob in result["problems"][:5]:
            print(f"    - {prob}")
    u = result["usage"]
    print(f"\n  tokens: {u['prompt_tokens']} in, {u['completion_tokens']} out")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tx_hash", nargs="+",
                    help="one or more transactions, or a single file with one "
                         "hash per line")
    ap.add_argument("--chain", default="eth", choices=sorted(config.RPC_ENV_BY_CHAIN),
                    help="which chain the transactions are on (default eth)")
    ap.add_argument("--condition", default="C3", choices=classify.CONDITIONS,
                    help="prompting condition (default C3, the best-informed one "
                         "that needs no ground truth about the victim)")
    ap.add_argument("--json", metavar="PATH", help="also write the full result as JSON")
    args = ap.parse_args()

    from pathlib import Path

    # A single argument naming a readable file is treated as a list of hashes,
    # so a batch of incidents can be handed over in one go.
    only = Path(args.tx_hash[0]) if len(args.tx_hash) == 1 else None
    if only is not None and only.is_file():
        hashes = [ln.strip() for ln in only.read_text(encoding="utf-8").splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]
    else:
        hashes = list(args.tx_hash)

    results, failed = [], []
    for i, tx in enumerate(hashes, 1):
        if len(hashes) > 1:
            print('\n========================================================================\n' + f"[{i}/{len(hashes)}] {tx}" + '\n========================================================================')
        try:
            result = analyse_transaction(tx, args.chain, args.condition)
        except SystemExit:
            raise
        except Exception as exc:
            # One bad transaction must not discard the analyses already done.
            print(f"  FAILED: {exc}")
            failed.append(tx)
            continue
        print_report(result)
        results.append(result)

    if len(hashes) > 1:
        print('\n' + f"{len(results)} analysed, {len(failed)} failed "
              + (str(failed) if failed else ""))

    if args.json:
        payload = results[0] if len(results) == 1 else results
        Path(args.json).write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                                   encoding="utf-8")
        print('\n  written: ' + args.json)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
