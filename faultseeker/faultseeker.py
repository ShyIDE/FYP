import requests
import json
from groq import Groq

ALCHEMY_URL  = "" #https://eth-mainnet.g.alchemy.com/v2/3tzfFButyH4ZP-03XQN34
GROQ_KEY     = "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"

# ── STEP 1: Pull transaction data ─────────────────────────────────────────────
def get_trace(tx_hash):
    print(f"\n[1] Fetching trace for {tx_hash[:20]}...")

    rpcs = [
        "https://ethereum.publicnode.com",
        "https://rpc.ankr.com/eth",
        "https://eth.llamarpc.com",
    ]

    receipt = None
    tx = None

    for rpc in rpcs:
        try:
            print(f"    Trying {rpc}...")
            r1 = requests.post(rpc, json={
                "id": 1, "jsonrpc": "2.0",
                "method": "eth_getTransactionReceipt",
                "params": [tx_hash]
            }, timeout=15)
            result = r1.json().get("result")
            if result:
                receipt = result
                print(f"    Got receipt from {rpc}")
                break
        except Exception as e:
            print(f"    Failed: {e}")
            continue

    for rpc in rpcs:
        try:
            r2 = requests.post(rpc, json={
                "id": 2, "jsonrpc": "2.0",
                "method": "eth_getTransactionByHash",
                "params": [tx_hash]
            }, timeout=15)
            result = r2.json().get("result")
            if result:
                tx = result
                break
        except Exception:
            continue

    if not receipt:
        print("    All RPCs failed — using sample data.")
        return {
            "receipt": {
                "gasUsed": "0x4C4B40",
                "logs": [
                    {"address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                     "topics": ["0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"]},
                    {"address": "0xd9fAb70159D79734b0f5523f72DF25e57e34D49",
                     "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"]},
                    {"address": "0xd9fAb70159D79734b0f5523f72DF25e57e34D49",
                     "topics": ["0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"]},
                    {"address": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
                     "topics": ["0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"]},
                    {"address": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
                     "topics": ["0x0d7d75e01ab95780d3cd1c8ec0dd6c2ce19e3a20427eec8bf53283b6fb8e95f0"]},
                    {"address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                     "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"]},
                    {"address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                     "topics": ["0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"]},
                    {"address": "0xd9fAb70159D79734b0f5523f72DF25e57e34D49",
                     "topics": ["0x3ab23ab0d51cccc0c3771aab4f562892b8b30db0e4d091f141e41db3b9e9df6e"]},
                    {"address": "0xd9fAb70159D79734b0f5523f72DF25e57e34D49",
                     "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"]},
                    {"address": "0xb66cd966670d962C227B3EABA30a872DbFb995db",
                     "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"]},
                ]
            },
            "tx": {
                "from": "0xb66cd966670d962C227B3EABA30a872DbFb995db",
                "to":   "0xd9fAb70159D79734b0f5523f72DF25e57e34D49",
                "input": "0x67c354b5",
                "value": "0x0",
                "hash":  tx_hash
            }
        }

    logs = receipt.get("logs", [])
    print(f"    Found {len(logs)} event logs.")
    return {"receipt": receipt, "tx": tx}


# ── STEP 2: Flatten into call frame list ──────────────────────────────────────
def flatten_calls(trace):
    result = []
    receipt = trace.get("receipt", {})
    tx      = trace.get("tx", {})
    logs    = receipt.get("logs", [])

    result.append({
        "depth": 0,
        "type":  "CALL",
        "from":  (tx.get("from") or "")[-8:],
        "to":    (tx.get("to")   or "")[-8:],
        "input": (tx.get("input") or "")[:10],
        "value": tx.get("value", "0x0"),
        "gas":   int(receipt.get("gasUsed", "0x0"), 16),
    })

    for i, log in enumerate(logs):
        topics   = log.get("topics", ["0x"])
        selector = topics[0][:10] if topics else "0x"
        result.append({
            "depth": 1,
            "type":  "EVENT",
            "from":  "internal",
            "to":    (log.get("address") or "")[-8:],
            "input": selector,
            "value": "0x0",
            "gas":   0,
        })

    return result


# ── STEP 3A: Zero-shot classification ─────────────────────────────────────────
def classify_with_llm(calls, tx_hash):
    print(f"\n[2] Classifying {len(calls)} frames — ZERO-SHOT mode...")

    client = Groq(api_key=GROQ_KEY)

    calls_text = ""
    for i, c in enumerate(calls[:40]):
        indent = "  " * c["depth"]
        calls_text += (
            f"{i+1}. {indent}[{c['type']}] "
            f"from=...{c['from']} to=...{c['to']} "
            f"selector={c['input']} gas={c['gas']}\n"
        )

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[
            {
                "role": "system",
                "content": "You are a DeFi security expert performing "
                           "forensic analysis of blockchain exploit transactions."
            },
            {
                "role": "user",
                "content": f"""Analyze this DeFi exploit transaction and classify each call frame.

Transaction hash: {tx_hash}

Classify each call frame as exactly ONE of:
  PREPARATORY  - Setup before exploit (flash loans, approvals, liquidity checks)
  TRIGGER      - Core exploit mechanism (reentrancy, oracle manipulation, unauthorized call)
  EXTRACTION   - Financial gain realisation (token drain, swap to profit, fund transfer)

CALL FRAMES:
{calls_text}

Respond in this EXACT format:
CALL 1: PREPARATORY - [one sentence explanation]
CALL 2: TRIGGER - [one sentence explanation]
...

Then finish with:
SUMMARY: [2-3 sentences explaining the full exploit mechanism]
VULNERABILITY TYPE: [e.g. Flash loan + Oracle manipulation]
ESTIMATED IMPACT: [financial impact if determinable]"""
            }
        ],
        max_tokens=2000
    )

    return response.choices[0].message.content


# ── STEP 3B: Few-shot classification ──────────────────────────────────────────
def classify_with_llm_fewshot(calls, tx_hash):
    print(f"\n[2] Classifying {len(calls)} frames — FEW-SHOT mode...")

    client = Groq(api_key=GROQ_KEY)

    # Curated examples — one per role
    examples = """EXAMPLES (annotated ground-truth for your reference):

CALL A: PREPARATORY - AaveV2 flashLoan() acquires a large capital position \
for the exploit without the attacker needing upfront funds; this is a \
standard preparatory action in flash loan-based attacks.

CALL B: TRIGGER - VulnerablePool withdraw() is called recursively before \
the internal balance mapping is updated, constituting the reentrancy \
vulnerability trigger that allows repeated fund withdrawal.

CALL C: EXTRACTION - A standard ERC-20 Transfer event (selector 0xddf252ad) \
moves tokens from the victim contract to the attacker address, directly \
realising the financial gain of the exploit.

Now classify the following call frames using the same format:
"""

    calls_text = ""
    for i, c in enumerate(calls[:40]):
        indent = "  " * c["depth"]
        calls_text += (
            f"{i+1}. {indent}[{c['type']}] "
            f"from=...{c['from']} to=...{c['to']} "
            f"selector={c['input']} gas={c['gas']}\n"
        )

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[
            {
                "role": "system",
                "content": "You are a DeFi security expert performing "
                           "forensic analysis of blockchain exploit transactions."
            },
            {
                "role": "user",
                "content": f"""Analyze this DeFi exploit transaction.

Transaction hash: {tx_hash}

Classify each call frame as exactly ONE of:
  PREPARATORY  - Setup before exploit (flash loans, approvals, liquidity checks)
  TRIGGER      - Core exploit mechanism (reentrancy, oracle manipulation, unauthorized call)
  EXTRACTION   - Financial gain realisation (token drain, swap to profit, fund transfer)

{examples}

CALL FRAMES:
{calls_text}

Respond in this EXACT format:
CALL 1: PREPARATORY - [one sentence explanation]
CALL 2: TRIGGER - [one sentence explanation]
...

Then finish with:
SUMMARY: [2-3 sentences explaining the full exploit mechanism]
VULNERABILITY TYPE: [e.g. Flash loan + Oracle manipulation]
ESTIMATED IMPACT: [financial impact if determinable]"""
            }
        ],
        max_tokens=2000
    )

    return response.choices[0].message.content


# ── STEP 4: Save output to file ───────────────────────────────────────────────
def save_output(filename_suffix, calls, classification):
    filename = f"trace_{filename_suffix}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write("FAULTSEEKER — DeFi Exploit Trace Analyser\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Total frames: {len(calls)}\n\n")
        f.write("RAW CALL FRAMES\n" + "-" * 40 + "\n")
        for i, c in enumerate(calls[:40]):
            indent = "  " * c["depth"]
            f.write(
                f"{i+1:>3}. {indent}[{c['type']}] "
                f"...{c['to']}  sel={c['input']}  gas={c['gas']}\n"
            )
        f.write("\nLLM CLASSIFICATION\n" + "-" * 40 + "\n")
        f.write(classification)

    print(f"\n    Saved to {filename}")
    return filename


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TX_HASH = "0xc310a0affe2169d1f6feec1c63dbc7f7c62a887521529ac1d8dc67698965cc70"

    print("=" * 60)
    print("  FAULTSEEKER — DeFi Exploit Trace Analyser")
    print("=" * 60)

    # Fetch trace
    trace = get_trace(TX_HASH)
    if not trace:
        print("Failed to fetch trace.")
        exit()

    calls = flatten_calls(trace)
    print(f"    Found {len(calls)} total call frames.")

    # ── Zero-shot ──
    print("\n" + "=" * 60)
    print("  ZERO-SHOT MODE")
    print("=" * 60)
    zs_output = classify_with_llm(calls, TX_HASH)
    print(zs_output)
    save_output("zeroshot", calls, zs_output)

    # ── Few-shot ──
    print("\n" + "=" * 60)
    print("  FEW-SHOT MODE")
    print("=" * 60)
    fs_output = classify_with_llm_fewshot(calls, TX_HASH)
    print(fs_output)
    save_output("fewshot", calls, fs_output)

    print("\n" + "=" * 60)
    print("  Done. Check trace_zeroshot.txt and trace_fewshot.txt")
    print("=" * 60)