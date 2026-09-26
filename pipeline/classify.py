"""Step 7: label every call in a transaction by prompting condition.

Each condition adds exactly one thing to the one before it, so any change in
the numbers can be attributed to that one addition:

    C0  rule baseline, no model: transparent lexical and structural rules
    C1  model, names masked: call-graph structure only
    C2  + decoded contract addresses and function names
    C3  + which address is the attacker and which is the attack contract
    C4  + few-shot examples taken from annotated dev cases only
    C5  + the victim contract's verified source

Two deliberate choices about what a condition may see:

- The victim contract's identity comes from the benchmark ground truth, so it
  is withheld until C5. C3 reveals only the attacker's account and the attack
  contract, both of which are readable from the transaction itself.
- C4's few-shot examples come from dev cases only. Test cases never appear in
  a prompt.

Output: data/predictions/<condition>_run<N>.json, one record per case, with
the raw model reply kept alongside the parsed labels so any number in the
report can be traced back to what the model actually said.

Usage
    python pipeline/classify.py --condition C2 --split dev
    python pipeline/classify.py --condition C2 --all --runs 3
    python pipeline/classify.py --condition C0 --all          # no API calls
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone

import requests

import config
import frame_context as fc

MODEL = "qwen/qwen3.8-27b"
TEMPERATURE = 0.0
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
CONDITIONS = ("C0", "C1", "C2", "C3", "C4", "C5")

# Argument and event text is clipped to the same width for every case, so a
# large transaction is not described more thinly than a small one.
ARGS_CLIP = 48
EVENTS_CLIP = 48
SOURCE_CLIP = 5000   # per victim contract, for C5

# The provider allows 7000 input tokens per minute and refuses outright any
# single request above that. Hex-heavy trace text tokenises at roughly two
# characters per token, so the call list is split into windows that stay under
# budget. Every case goes through the same windowing code: a small case simply
# yields one window, so the procedure does not differ between cases.
CALL_BUDGET_TOKENS = 2600
CHARS_PER_TOKEN = 2.0
# The provider also caps output at 1000 tokens per minute and rejects a
# request whose expected output exceeds it. One label costs roughly 20
# tokens, so a window is capped at 40 calls and max_tokens is set
# explicitly rather than left to the provider's own estimate.
MAX_CALLS_PER_WINDOW = 40
MAX_OUTPUT_TOKENS = 950
# Few-shot examples are capped, and the smallest dev cases are chosen, because
# each one is added to every request and the daily token budget is 200,000.
FEWSHOT_CASES = 2

# C0 baseline lexicons. Deliberately shallow: this is the floor that the
# prompting conditions have to beat, not a serious classifier.
EXTRACTION_WORDS = ("transfer", "withdraw", "redeem", "repay", "swap", "send",
                    "sweep", "claim", "collect", "skim", "burn")
PREPARATORY_WORDS = ("approve", "flashloan", "borrow", "deposit", "mint", "balanceof",
                     "getreserves", "allowance", "totalsupply", "decimals", "price",
                     "symbol", "name", "log")

SYSTEM = (
    "You label the calls inside a single blockchain attack transaction. "
    "For every call you assign one role and one essentiality flag.\n\n"
    "Roles:\n"
    "PREPARATORY - sets up the conditions the exploit needs: taking a flash loan, "
    "approvals, deploying helper contracts, reading state to size the attack, "
    "swaps that acquire the asset the exploit needs.\n"
    "TRIGGER - exploits the vulnerability itself. The test: if this call were "
    "removed and nothing else changed, the attack would stop working.\n"
    "EXTRACTION - realises or secures the profit after the vulnerability has "
    "been exploited: draining balances, swapping stolen value out, repaying the "
    "flash loan, moving funds to the attacker.\n\n"
    "Rules: taking a flash loan is PREPARATORY but repaying it is EXTRACTION. "
    "A read-only call is almost always PREPARATORY, unless the victim relies on "
    "the value it returns. A delegatecall keeps the role of the call that "
    "entered the proxy. Repetition does not change a role: forty copies of the "
    "same exploit call are all TRIGGER. Judge by effect, not by function name.\n\n"
    "essential is yes if removing the call would make the attack fail or lose "
    "value, and no otherwise. Every TRIGGER call is essential.\n\n"
    "Reply with JSON only, no prose and no code fence, as "
    '{"labels":[{"index":<int>,"role":"PREPARATORY|TRIGGER|EXTRACTION",'
    '"essential":"yes|no"}]}. Label every index you are given, exactly once.'
)


# ---------------------------------------------------------------- prompting
def render_calls(rows: list[dict], condition: str) -> str:
    masks = fc.mask_map(rows) if condition == "C1" else None
    lines = []
    for row in rows:
        line = f"{row['index']:>4}. {fc.tree_label(row, masks)}"
        if condition != "C1":
            if row["args"]:
                line += "\n        args: " + row["args"][:ARGS_CLIP]
            if row["events"]:
                line += "\n        events: " + row["events"][:EVENTS_CLIP]
            if row["outcome"] and row["outcome"] != "Return":
                line += "\n        outcome: " + row["outcome"]
        lines.append(line)
    return "\n".join(lines)


def address_block(record: dict, condition: str) -> str:
    """Who the attacker is. Withheld before C3; never reveals the victim."""
    if condition in ("C1", "C2"):
        return ""
    roles = fc.address_roles(record)
    shown = {a: r for a, r in roles.items() if r in ("attacker", "attack_contract")}
    if not shown:
        return ""
    lines = [f"  {addr} = {role}" for addr, role in sorted(shown.items(), key=lambda kv: kv[1])]
    return "Known addresses in this transaction:\n" + "\n".join(lines) + "\n\n"


def fewshot_block(condition: str, examples: list[dict]) -> str:
    if condition not in ("C4", "C5") or not examples:
        return ""
    out = ["Worked examples from other attacks, labelled by a human annotator:\n"]
    for ex in examples:
        out.append(f"Attack: {ex['case_id']} ({ex['category']})")
        out.append(ex["calls"])
        out.append("Labels: " + json.dumps({"labels": ex["labels"]}, separators=(",", ":")))
        out.append("")
    return "\n".join(out) + "\n"


def victim_source_block(condition: str, sources: dict[str, str]) -> str:
    if condition != "C5" or not sources:
        return ""
    out = ["Verified source of the contract that was exploited:\n"]
    for addr, src in sources.items():
        out.append(f"--- {addr} ---")
        out.append(src[:SOURCE_CLIP])
        out.append("")
    return "\n".join(out) + "\n"


def est_tokens(text: str) -> int:
    """Conservative token estimate for trace text, which is mostly hex."""
    return int(len(text) / CHARS_PER_TOKEN) + 1


def chunk_rows(rows: list[dict], condition: str,
               budget: int = CALL_BUDGET_TOKENS) -> list[list[dict]]:
    """Split the calls into consecutive windows that each fit the budget."""
    windows: list[list[dict]] = []
    current: list[dict] = []
    used = 0
    for row in rows:
        cost = est_tokens(render_calls([row], condition))
        if current and (used + cost > budget or len(current) >= MAX_CALLS_PER_WINDOW):
            windows.append(current)
            current, used = [], 0
        current.append(row)
        used += cost
    if current:
        windows.append(current)
    return windows


def build_prompt(record: dict, condition: str, examples: list[dict],
                 sources: dict[str, str], window: list[dict] | None = None,
                 total: int | None = None) -> str:
    rows = fc.frame_rows(record)
    window = rows if window is None else window
    total = len(rows) if total is None else total
    case = record["case"]

    span = ""
    if len(window) != total:
        span = ("This is calls %d to %d of %d, in execution order. "
                "Label only the calls shown.\n"
                % (window[0]["index"], window[-1]["index"], total))

    if condition == "C1":
        header = ("Attack transaction with %d calls. Contract and function names "
                  "have been removed; only the call structure remains.\n"
                  "Indentation shows the call tree.\n%s\n" % (total, span))
    else:
        header = ("Attack transaction with %d calls, on %s.\n"
                  "Indentation shows the call tree; a nested line is a call made "
                  "by the line above it.\n%s\n" % (total, case["chain"], span))

    return (
        fewshot_block(condition, examples)
        + victim_source_block(condition, sources)
        + header
        + address_block(record, condition)
        + "Calls:\n" + render_calls(window, condition)
        + "\n\nLabel all %d calls shown. JSON only." % len(window)
    )


# ---------------------------------------------------------------- the model
def _parse_reset(value: str | None) -> float:
    """Groq reports resets like '23.134s' or '5m45.6s'."""
    if not value:
        return 0.0
    total, num = 0.0, ""
    for ch in value:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch == "m":
            total += float(num or 0) * 60
            num = ""
        elif ch == "s":
            total += float(num or 0)
            num = ""
    return total + (float(num) if num else 0.0)


class RateLimiter:
    """Keeps requests inside the provider's input-tokens-per-minute budget.

    A single large trace is a large fraction of the per-minute allowance, so
    requests are paced from the limit headers the provider returns rather than
    by guessing a fixed delay.
    """

    def __init__(self) -> None:
        self.remaining_tokens: int | None = None
        self.reset_after: float = 0.0

    def wait_if_needed(self, want_tokens: int) -> None:
        if self.remaining_tokens is None:
            return
        if self.remaining_tokens < want_tokens:
            nap = max(1.0, self.reset_after) + 1.0
            print(f"    token budget low ({self.remaining_tokens} left, "
                  f"need ~{want_tokens}); waiting {nap:.0f}s")
            time.sleep(nap)
            self.remaining_tokens = None

    def update(self, headers) -> None:
        try:
            self.remaining_tokens = int(headers.get("x-ratelimit-remaining-tokens", ""))
        except (TypeError, ValueError):
            self.remaining_tokens = None
        self.reset_after = _parse_reset(headers.get("x-ratelimit-reset-tokens"))


LIMITER = RateLimiter()


def call_groq(prompt: str, attempts: int = 6) -> dict:
    key = config.require("GROQ_API_KEY")
    body = {
        "model": MODEL,
        "temperature": TEMPERATURE,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "max_tokens": MAX_OUTPUT_TOKENS,
    }
    estimate = est_tokens(prompt + SYSTEM) + 200
    for attempt in range(1, attempts + 1):
        LIMITER.wait_if_needed(estimate)
        try:
            r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"},
                              json=body, timeout=300)
        except requests.RequestException as exc:
            if attempt < attempts:
                wait = min(60, 2 ** attempt)
                print(f"    {type(exc).__name__}; retrying in {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Groq request failed: {exc}") from None

        LIMITER.update(r.headers)
        if r.status_code == 200:
            return r.json()

        # Only throttling and server faults are worth retrying: a 400 or a 413
        # fails the same way every time, so surface it instead of looping.
        if r.status_code == 429 and attempt < attempts:
            nap = (_parse_reset(r.headers.get("retry-after"))
                   or _parse_reset(r.headers.get("x-ratelimit-reset-tokens"))
                   or float(2 ** attempt))
            print(f"    rate limited; waiting {nap:.0f}s")
            time.sleep(min(nap + 1, 120))
            continue
        if r.status_code in (500, 502, 503, 504) and attempt < attempts:
            wait = min(60, 2 ** attempt)
            print(f"    {r.status_code} from Groq; retrying in {wait}s")
            time.sleep(wait)
            continue
        try:
            detail = r.json().get("error", {}).get("message", "")[:300]
        except ValueError:
            detail = r.text[:300]
        raise RuntimeError(f"Groq returned {r.status_code}: {detail}")
    raise RuntimeError("Groq request failed after retries")


def parse_labels(text: str, valid: set[int]) -> tuple[dict[int, dict], list[str]]:
    """Parse the model's JSON. Records problems instead of silently fixing them."""
    problems: list[str] = []
    blob = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        m = re.search(r"\{.*\}", blob, re.S)
        if not m:
            return {}, [f"reply was not JSON: {exc}"]
        try:
            data = json.loads(m.group(0))
            problems.append("JSON needed extraction from surrounding text")
        except json.JSONDecodeError as exc2:
            return {}, [f"reply was not JSON: {exc2}"]

    items = data.get("labels") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {}, ["no 'labels' list in the reply"]

    out: dict[int, dict] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            idx = int(it.get("index"))
        except (TypeError, ValueError):
            continue
        role = str(it.get("role", "")).strip().upper()
        ess = str(it.get("essential", "")).strip().lower()
        if idx not in valid:
            problems.append(f"index {idx} is not a call in this window")
            continue
        if role not in fc.ROLES:
            problems.append(f"index {idx}: unknown role {role!r}")
            role = ""
        if ess not in fc.ESSENTIAL:
            problems.append(f"index {idx}: unknown essential {ess!r}")
            ess = ""
        if idx in out:
            problems.append(f"index {idx} labelled more than once")
        out[idx] = {"role": role, "essential": ess}

    missing = sorted(valid - set(out))
    if missing:
        problems.append(f"{len(missing)} calls not labelled in this window: {missing[:20]}")
    return out, problems


# ---------------------------------------------------------------- baseline
def rule_baseline(rows: list[dict]) -> dict[int, dict]:
    """C0: transparent lexical and structural rules. Uses no ground truth."""
    out = {}
    for row in rows:
        fn = row["function"].lower()
        if row["kind"] == "CREATE":
            role, ess = "PREPARATORY", "yes"
        elif row["kind"] == "STATICCALL":
            role, ess = "PREPARATORY", "no"
        elif any(w in fn for w in EXTRACTION_WORDS):
            role, ess = "EXTRACTION", "yes"
        elif any(w in fn for w in PREPARATORY_WORDS):
            role, ess = "PREPARATORY", "yes"
        else:
            role, ess = "TRIGGER", "yes"
        out[row["index"]] = {"role": role, "essential": ess}
    return out


# ---------------------------------------------------------------- few-shot
def load_fewshot(condition: str) -> list[dict]:
    """Few-shot examples from annotated dev cases. Fails loudly if unavailable."""
    if condition not in ("C4", "C5"):
        return []
    ann = config.DATA_DIR / "annotation"
    rows, source = [], None
    # Prefer labels a human stands behind. Fall back to the drafted sheet, but
    # record which was used: a run prompted with drafted labels must be
    # described that way in the report.
    for name, need_reviewed in (("sheet.csv", False), ("sheet_draft.csv", True),
                                ("sheet_draft.csv", False)):
        path = ann / name
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig") as fh:
            found = [r for r in csv.DictReader(fh)
                     if r["split"] == "dev" and r["role"].strip() and r["essential"].strip()
                     and (not need_reviewed
                          or r.get("reviewed", "").strip().lower() == "yes")]
        if found:
            rows = found
            source = f"{name}{' (reviewed only)' if need_reviewed else ''}"
            break
    if not rows:
        sys.exit(f"{condition} needs labelled dev cases for its examples. Run "
                 f"pipeline/draft_annotations.py, or fill in {ann / 'sheet.csv'}. "
                 f"No example may be invented.")
    print(f"few-shot label source: {source}")

    by_case: dict[str, list[dict]] = {}
    for r in rows:
        by_case.setdefault(r["case_id"], []).append(r)

    cases = fc.load_cases()
    examples = []
    for case_id in sorted(by_case):
        record = fc.load_record(cases[case_id])
        frames = fc.frame_rows(record)
        labelled = {int(r["frame_index"]): r for r in by_case[case_id]}
        if len(labelled) != len(frames):
            continue  # only fully annotated cases make usable examples
        examples.append({
            "case_id": case_id,
            "category": cases[case_id]["category"],
            "calls": render_calls(frames, "C2"),
            "labels": [{"index": f["index"],
                        "role": labelled[f["index"]]["role"].strip().upper(),
                        "essential": labelled[f["index"]]["essential"].strip().lower()}
                       for f in frames],
        })
    if not examples:
        sys.exit(f"{condition} found labelled dev rows but no dev case is fully "
                 f"labelled. Complete at least one dev case.")
    examples.sort(key=lambda e: len(e["labels"]))
    return examples[:FEWSHOT_CASES]


def load_victim_sources(record: dict, condition: str) -> dict[str, str]:
    if condition != "C5":
        return {}
    from fetch_sources import cached_source  # imported late: only C5 needs it
    case = record["case"]
    out = {}
    for addr in case.get("gt_vuln_contracts", "").split(";"):
        addr = addr.strip()
        if addr:
            out[addr] = cached_source(addr, case["chain"])
    return out


# ---------------------------------------------------------------- driver
def run_case(case: dict, condition: str, run: int, examples: list[dict]) -> dict:
    record = fc.load_record(case)
    rows = fc.frame_rows(record)
    valid = {r["index"] for r in rows}
    started = time.time()

    if condition == "C0":
        labels, problems, usage, raw = rule_baseline(rows), [], {}, ""
        n_windows = 1
    else:
        sources = load_victim_sources(record, condition)
        chunks = chunk_rows(rows, condition)
        n_windows = len(chunks)
        labels, problems, raw_parts = {}, [], []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for chunk in chunks:
            prompt = build_prompt(record, condition, examples, sources,
                                  window=chunk, total=len(rows))
            reply = call_groq(prompt)
            text = reply["choices"][0]["message"]["content"]
            raw_parts.append(text)
            for k in usage:
                usage[k] += reply.get("usage", {}).get(k, 0)
            part, probs = parse_labels(text, {r["index"] for r in chunk})
            labels.update(part)
            problems.extend(probs)
        raw = "\n---\n".join(raw_parts)
        missing = sorted(valid - set(labels))
        if missing:
            problems.append(f"{len(missing)} calls unlabelled overall: {missing[:20]}")

    return {
        "case_id": case["case_id"], "category": case["category"], "split": case["split"],
        "condition": condition, "run": run,
        "model": MODEL if condition != "C0" else "rules",
        "temperature": TEMPERATURE, "n_calls": len(rows), "windows": n_windows,
        "labels": {str(k): v for k, v in sorted(labels.items())},
        "problems": problems,
        "usage": usage,
        "seconds": round(time.time() - started, 2),
        "raw_reply": raw,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def merge_write(path, records: list[dict]) -> list[dict]:
    """Merge records into the file on disk and write it.

    Called after every case, not only at the end of a run. A run is routinely
    cut short by the daily token limit, and finishing twenty cases only to lose
    them because the twenty-first could not start is not acceptable.
    """
    merged = {}
    if path.exists():
        for old_rec in json.loads(path.read_text(encoding="utf-8")):
            merged[old_rec["case_id"]] = old_rec
    for rec in records:
        merged[rec["case_id"]] = rec
    ordered = [merged[k] for k in sorted(merged)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ordered, indent=1, ensure_ascii=False), encoding="utf-8")
    return ordered


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--condition", required=True, choices=CONDITIONS)
    pick = ap.add_mutually_exclusive_group(required=True)
    pick.add_argument("--case")
    pick.add_argument("--split", choices=["dev", "test"])
    pick.add_argument("--all", action="store_true")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--verified-only", action="store_true",
                    help="skip cases whose replay did not match the receipt")
    ap.add_argument("--only-missing", action="store_true",
                    help="skip cases already present in the output file")
    args = ap.parse_args()

    cases = fc.load_cases()
    if args.case:
        if args.case not in cases:
            sys.exit(f"No case {args.case}")
        chosen = [cases[args.case]]
    elif args.split:
        chosen = [c for c in cases.values() if c["split"] == args.split]
    else:
        chosen = list(cases.values())
    chosen.sort(key=lambda c: c["case_id"])

    if args.verified_only:
        chosen = [c for c in chosen if fc.load_record(c)["summary"]["replay_faithful"]]
        print(f"verified-only: {len(chosen)} cases")

    if args.only_missing:
        done_path = config.DATA_DIR / "predictions" / f"{args.condition}_run1.json"
        if done_path.exists():
            have = {r["case_id"] for r in json.loads(done_path.read_text(encoding="utf-8"))}
            before = len(chosen)
            chosen = [c for c in chosen if c["case_id"] not in have]
            print(f"only-missing: {len(chosen)} of {before} cases still to do")

    examples = load_fewshot(args.condition)
    if examples:
        print(f"few-shot examples from dev cases: {[e['case_id'] for e in examples]}")

    out_dir = config.DATA_DIR / "predictions"
    out_dir.mkdir(parents=True, exist_ok=True)

    for run in range(1, args.runs + 1):
        records, failed = [], []
        print(f"\n=== {args.condition} run {run}/{args.runs} ===")
        for case in chosen:
            try:
                rec = run_case(case, args.condition, run, examples)
                flag = "" if not rec["problems"] else f"  [{len(rec['problems'])} problem(s)]"
                print(f"  {case['case_id']:4} {len(rec['labels'])}/{rec['n_calls']} labelled  "
                      f"{rec['windows']}w  {rec['seconds']}s{flag}")
                for p in rec["problems"][:2]:
                    print(f"       - {p}")
                records.append(rec)
                merge_write(out_dir / f"{args.condition}_run{run}.json", records)
            except Exception as exc:
                print(f"  {case['case_id']:4} FAILED: {exc}")
                failed.append(case["case_id"])

        path = out_dir / f"{args.condition}_run{run}.json"
        ordered = merge_write(path, records)
        print(f"  -> {path}  ({len(records)} this run, {len(ordered)} in file, "
              f"{len(failed)} failed)")
        if failed:
            print(f"  FAILED: {failed}")


if __name__ == "__main__":
    main()
