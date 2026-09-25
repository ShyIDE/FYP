"""Shared view of a parsed transaction: address roles and per-frame rows.

Both the annotation sheet and the classifier read frames through this module,
so a human annotator and the model see the same facts about the same call.

Address roles are derived from the transaction itself and from the benchmark's
ground-truth vulnerable contracts. Nothing here is guessed: if an address is
not the attacker, the attack contract or a recorded victim, it is left
unlabelled.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import config

ROLES = ("PREPARATORY", "TRIGGER", "EXTRACTION")
ESSENTIAL = ("yes", "no")


def load_cases() -> dict[str, dict]:
    with open(config.CASES_CSV, encoding="utf-8") as fh:
        return {r["case_id"]: r for r in csv.DictReader(fh)}


def load_record(case: dict) -> dict:
    """Return the parsed frames record for a case, or raise if it is missing."""
    path = config.FRAMES_DIR / f"{case['tx_hash'].lower()}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No frames for {case['case_id']}. Run: python pipeline/fetch_traces.py "
            f"--case {case['case_id']}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def address_roles(record: dict) -> dict[str, str]:
    """Map lowercase address -> one of attacker / attack_contract / victim.

    attacker        the externally owned account that sent the transaction
    attack_contract the contract it called, or the contract it deployed when
                    the transaction is a contract creation
    victim          a contract named in the benchmark's ground truth
    """
    onchain, case = record["onchain"], record["case"]
    roles: dict[str, str] = {}

    attacker = (onchain.get("from") or "").lower()
    if attacker:
        roles[attacker] = "attacker"

    target = (onchain.get("to") or "").lower()
    if not target:
        # contract-creation transaction: the deployed contract is the root frame
        root = record["frames"][0]
        target = (root.get("target_address") or "").lower()
    if target:
        roles[target] = "attack_contract"

    for addr in case.get("gt_vuln_contracts", "").split(";"):
        addr = addr.strip().lower()
        if addr:
            roles.setdefault(addr, "victim")
    return roles


def gt_function_set(case: dict) -> set[str]:
    return {f.strip().lower() for f in case.get("gt_vuln_functions", "").split(";") if f.strip()}


def frame_rows(record: dict) -> list[dict]:
    """One row per call frame, with the context needed to judge its purpose."""
    case = record["case"]
    roles = address_roles(record)
    gt_fns = gt_function_set(case)
    gt_addrs = {a.strip().lower() for a in case.get("gt_vuln_contracts", "").split(";") if a.strip()}

    rows = []
    for fr in record["frames"]:
        addr = (fr.get("target_address") or "").lower()
        fn = fr["function"].lower()
        is_gt = fn in gt_fns and (not gt_addrs or not addr or addr in gt_addrs)
        rows.append({
            "index": fr["index"],
            "depth": fr["depth"],
            "parent": fr["parent"],
            "kind": fr["kind"],
            "target": fr["target"],
            "target_address": fr.get("target_address"),
            "target_role": roles.get(addr, ""),
            "function": fr["function"],
            "decoded": fr["decoded"],
            "args": fr["args"],
            "value": fr["value"],
            "gas": fr["gas"],
            "outcome": fr["outcome"],
            "return_data": fr["return_data"],
            "events": " | ".join(fr["events"]),
            "n_children": fr["n_children"],
            "is_gt_vuln_function": is_gt,
        })
    return rows


def mask_map(rows: list[dict]) -> dict[str, str]:
    """Stable placeholder per distinct callee, numbered in order of appearance.

    Built from the rows themselves rather than from hash(), which is salted per
    process and would make masked runs irreproducible.
    """
    mapping: dict[str, str] = {}
    for row in rows:
        key = (row["target_address"] or row["target"]).lower()
        if key not in mapping:
            mapping[key] = f"ADDR{len(mapping) + 1:03d}"
    return mapping


def tree_label(row: dict, masks: dict[str, str] | None = None) -> str:
    """A one-line, indented rendering of a call, as shown to humans and models.

    Passing the map from mask_map() replaces every identifier with a stable
    placeholder, leaving only the call-graph structure. This is condition C1.
    """
    indent = "  " * row["depth"]
    if masks is not None:
        who = masks[(row["target_address"] or row["target"]).lower()]
        what = "FN" if row["decoded"] else "UNKNOWN_FN"
        return f"{indent}[{row['kind']}] {who}.{what}()"
    target = row["target_address"] or row["target"]
    short = target if len(target) <= 12 else f"{target[:8]}..{target[-4:]}"
    val = f" value={row['value']}" if row["value"] else ""
    return f"{indent}[{row['kind']}] {short}.{row['function']}(){val}"
