"""Step 2/3: replay each study transaction with Foundry and save its call trace.

For every case in data/cases.csv this script:
  1. Looks the transaction up on-chain (fails loudly if the hash is wrong).
  2. Replays it with `cast run` and saves the raw text to data/traces/<hash>.txt
  3. Parses the call tree into data/frames/<hash>.json
  4. Checks replay fidelity: the replayed gas and success/failure must match
     the on-chain receipt. `--quick` replays skip earlier transactions in the
     block (as FaultSeeker does); if they diverge, the script re-runs a full
     replay automatically.
  5. Reports where the ground-truth vulnerable function appears in the trace.

There is no fallback data: if anything fails, the case is marked failed and
nothing is written for it.

Usage (from the repo root, in Git Bash):
    python pipeline/fetch_traces.py --case C16         # one case (Euler)
    python pipeline/fetch_traces.py --split dev        # the 7 dev cases
    python pipeline/fetch_traces.py --all              # all 28 cases
    add --force to redo cases that already have a frames file
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

import config
from trace_parser import parse_trace

GAS_TOLERANCE = 0.001  # replayed gas may differ from the receipt by at most 0.1%


def redact(text: str) -> str:
    """Strip API keys out of anything that may be printed or logged.

    RPC URLs carry the key in the path, and requests puts the full URL in its
    exception messages, so an unredacted error prints the key to the terminal.
    """
    return re.sub(r"(https?://[^/\s]+/)[^\s'\"]*", r"\1<redacted>", text)


def rpc_call(url: str, method: str, params: list, attempts: int = 5):
    """POST a JSON-RPC call, retrying throttling and transient server errors.

    Every error is re-raised with the URL redacted so the key never reaches
    the terminal or a log file.
    """
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                            "params": params}, timeout=60)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < attempts:
                wait = 2 ** attempt
                print(f"  RPC {resp.status_code} from the provider; retrying in {wait}s "
                      f"({attempt}/{attempts - 1})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:
                raise RuntimeError(f"{method} failed: {redact(str(body['error']))}")
            return body.get("result")
        except requests.RequestException as exc:
            if attempt < attempts:
                wait = 2 ** attempt
                print(f"  RPC call failed ({type(exc).__name__}); retrying in {wait}s "
                      f"({attempt}/{attempts - 1})")
                time.sleep(wait)
                continue
            raise RuntimeError(f"{method} failed: {redact(str(exc))}") from None
    raise RuntimeError(f"{method} failed after {attempts} attempts")


def onchain_facts(url: str, tx_hash: str) -> dict:
    tx = rpc_call(url, "eth_getTransactionByHash", [tx_hash])
    receipt = rpc_call(url, "eth_getTransactionReceipt", [tx_hash])
    if not tx or not receipt:
        raise RuntimeError("transaction not found on this chain: check the hash and the RPC URL")
    return {
        "from": tx["from"], "to": tx.get("to"), "block": int(tx["blockNumber"], 16),
        "receipt_gas_used": int(receipt["gasUsed"], 16),
        "receipt_status": "success" if receipt["status"] == "0x1" else "failed",
        "n_logs": len(receipt.get("logs", [])),
    }


def find_cast() -> str:
    cast = os.environ.get("CAST_BIN") or shutil.which("cast")
    if not cast:
        sys.exit("`cast` not found. Install Foundry (README, Step 2) and run this from Git Bash.")
    return cast


def run_cast(cast: str, tx_hash: str, url: str, quick: bool) -> str:
    cmd = [cast, "run", tx_hash, "--rpc-url", url] + (["--quick"] if quick else [])
    env = dict(os.environ, NO_COLOR="1")
    key = config.optional("ETHERSCAN_API_KEY")
    if key:
        env["ETHERSCAN_API_KEY"] = key
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=3600)
    if proc.returncode != 0 or "Traces:" not in proc.stdout:
        detail = redact((proc.stderr or proc.stdout)[-1500:])
        raise RuntimeError(f"cast run failed (exit {proc.returncode}):\n{detail}")
    return proc.stdout


def fidelity(parsed: dict, facts: dict) -> tuple[bool, str]:
    g, r = parsed["cast_gas_used"], facts["receipt_gas_used"]
    if parsed["cast_status"] != facts["receipt_status"]:
        return False, f"status differs: replay {parsed['cast_status']} vs chain {facts['receipt_status']}"
    if g is None:
        return False, "cast did not report gas used"
    if abs(g - r) > GAS_TOLERANCE * r:
        return False, f"gas differs: replay {g} vs chain {r}"
    return True, f"gas matches chain ({g})"


def gt_matches(frames: list[dict], case: dict) -> list[int]:
    fns = {f.lower() for f in case["gt_vuln_functions"].split(";") if f}
    addrs = {a.lower() for a in case["gt_vuln_contracts"].split(";") if a}
    hits = []
    for fr in frames:
        fn = fr["function"].lower().removeprefix("0x")
        fn_ok = fn in {f.removeprefix("0x") for f in fns}
        addr = (fr["target_address"] or "").lower()
        if fn_ok and (not addr or not addrs or addr in addrs):
            hits.append(fr["index"])
    return hits


def process(case: dict, cast: str, force: bool) -> dict:
    tx, chain = case["tx_hash"].lower(), case["chain"]
    out_path = config.FRAMES_DIR / f"{tx}.json"
    if out_path.exists() and not force:
        print(f"{case['case_id']}: already done (use --force to redo)")
        return json.loads(out_path.read_text(encoding="utf-8"))["summary"]

    url = config.rpc_url(chain)
    print(f"{case['case_id']} {case['name']} ({chain}) {tx[:12]}...")
    facts = onchain_facts(url, tx)
    print(f"  on-chain: block {facts['block']}, {facts['receipt_status']}, gas {facts['receipt_gas_used']}")

    mode, raw = "quick", run_cast(cast, tx, url, quick=True)
    parsed = parse_trace(raw)
    ok, note = fidelity(parsed, facts)
    if not ok:
        print(f"  quick replay diverged ({note}); re-running full replay of the block...")
        mode, raw = "full", run_cast(cast, tx, url, quick=False)
        parsed = parse_trace(raw)
        ok, note = fidelity(parsed, facts)
    print(f"  replay ({mode}): {'OK' if ok else 'MISMATCH'} - {note}")

    frames = parsed["frames"]
    hits = gt_matches(frames, case)
    summary = {
        "case_id": case["case_id"], "name": case["name"], "category": case["category"],
        "split": case["split"], "chain": chain, "tx_hash": tx,
        "frames": len(frames), "max_depth": max(f["depth"] for f in frames),
        "staticcalls": sum(f["kind"] == "STATICCALL" for f in frames),
        "delegatecalls": sum(f["kind"] == "DELEGATECALL" for f in frames),
        "undecoded": sum(not f["decoded"] for f in frames),
        "events": sum(len(f["events"]) for f in frames),
        "replay_mode": mode, "replay_faithful": ok, "fidelity_note": note,
        "gt_functions": case["gt_vuln_functions"], "gt_frame_hits": ";".join(map(str, hits)),
    }
    config.TRACES_DIR.mkdir(parents=True, exist_ok=True)
    config.FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    (config.TRACES_DIR / f"{tx}.txt").write_text(raw, encoding="utf-8")
    record = {
        "case": case, "onchain": facts, "summary": summary, "frames": frames,
        "cast_gas_used": parsed["cast_gas_used"],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cast_version": subprocess.run([cast, "--version"], capture_output=True, text=True,
                                       encoding="utf-8", errors="replace").stdout.strip().splitlines()[0],
    }
    out_path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"  {summary['frames']} frames, depth {summary['max_depth']}, "
          f"{summary['staticcalls']} staticcalls, {summary['undecoded']} undecoded")
    print(f"  ground-truth function {case['gt_vuln_functions']!r} at frames: {summary['gt_frame_hits'] or 'NOT FOUND'}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    pick = ap.add_mutually_exclusive_group(required=True)
    pick.add_argument("--case", help="case id, e.g. C16")
    pick.add_argument("--split", choices=["dev", "test"])
    pick.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true", help="redo cases that already have output")
    args = ap.parse_args()

    with open(config.CASES_CSV, encoding="utf-8") as fh:
        cases = list(csv.DictReader(fh))
    if args.case:
        cases = [c for c in cases if c["case_id"].lower() == args.case.lower()]
        if not cases:
            sys.exit(f"No case {args.case} in {config.CASES_CSV}")
    elif args.split:
        cases = [c for c in cases if c["split"] == args.split]

    cast = find_cast()
    summaries, failed = [], []
    for case in cases:
        try:
            summaries.append(process(case, cast, args.force))
        except Exception as exc:  # keep going; report at the end
            print(f"  FAILED: {exc}")
            failed.append(case["case_id"])

    if summaries:
        path = config.FRAMES_DIR / "summary.csv"
        existing = {}
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                existing = {r["case_id"]: r for r in csv.DictReader(fh)}
        existing.update({s["case_id"]: s for s in summaries})
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(summaries[0].keys()))
            w.writeheader()
            w.writerows(sorted(existing.values(), key=lambda r: r["case_id"]))
        print(f"\nSummary table: {path}")
    unfaithful = [s["case_id"] for s in summaries if not s["replay_faithful"]]
    faithful = len(summaries) - len(unfaithful)
    print(f"Done: {faithful} verified, {len(unfaithful)} replay-mismatch, "
          f"{len(failed)} failed {failed if failed else ''}")
    if unfaithful:
        # A mismatched replay is not a usable result: the trace was produced,
        # but it does not provably reproduce the on-chain execution, so it
        # must not be treated as verified data.
        print(f"\nWARNING: the replay did not match the on-chain receipt for "
              f"{', '.join(unfaithful)}.")
        print("These are written with replay_faithful=false in summary.csv and must "
              "not be used as verified traces until the mismatch is explained.")
    if failed or unfaithful:
        sys.exit(1)


if __name__ == "__main__":
    main()
