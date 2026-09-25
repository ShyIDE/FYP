"""Fetch verified contract source for condition C5, and cache it.

Only C5 needs this. Sources come from Etherscan (which also serves BSC through
its multi-chain endpoint) and are cached under data/sources/ so a repeated run
does not refetch.

There is no fallback: if the key is missing, or the contract's source is not
verified, this raises. C5 must not run against invented or empty source.
"""
from __future__ import annotations

import json
import time

import requests

import config

API = "https://api.etherscan.io/v2/api"
CHAIN_IDS = {"eth": 1, "bsc": 56}
SOURCES_DIR = config.DATA_DIR / "sources"


def fetch_source(address: str, chain: str) -> str:
    key = config.optional("ETHERSCAN_API_KEY")
    if not key:
        raise RuntimeError(
            "C5 needs verified contract source, which needs ETHERSCAN_API_KEY in "
            ".env. Get a free key from etherscan.io and add it. Without it C5 "
            "cannot run; it must not fall back to an empty or invented source."
        )
    chain_id = CHAIN_IDS.get(chain.lower())
    if chain_id is None:
        raise RuntimeError(f"No Etherscan chain id for chain {chain!r}")

    params = {"chainid": chain_id, "module": "contract", "action": "getsourcecode",
              "address": address, "apikey": key}
    for attempt in range(1, 5):
        r = requests.get(API, params=params, timeout=60)
        r.raise_for_status()
        body = r.json()
        if body.get("status") == "1":
            break
        message = str(body.get("result", body.get("message", "")))
        if "rate limit" in message.lower() and attempt < 4:
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"Etherscan returned no source for {address}: {message[:200]}")
    else:
        raise RuntimeError(f"Etherscan rate limited while fetching {address}")

    entry = body["result"][0]
    source = entry.get("SourceCode") or ""
    if not source.strip():
        raise RuntimeError(
            f"{address} has no verified source on {chain}. C5 cannot be run for "
            f"this case; record it as excluded rather than substituting anything."
        )

    # Etherscan wraps multi-file (standard-json) sources in an extra pair of braces
    if source.startswith("{{"):
        try:
            parsed = json.loads(source[1:-1])
            files = parsed.get("sources", {})
            source = "\n\n".join(
                f"// file: {name}\n{blob.get('content', '')}" for name, blob in files.items())
        except (json.JSONDecodeError, AttributeError):
            pass  # keep the raw text; it is still the real source
    return source


def cached_source(address: str, chain: str) -> str:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCES_DIR / f"{chain}_{address.lower()}.sol"
    if path.exists():
        return path.read_text(encoding="utf-8")
    source = fetch_source(address, chain)
    path.write_text(source, encoding="utf-8")
    return source


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("usage: python pipeline/fetch_sources.py <address> <eth|bsc>")
        raise SystemExit(2)
    text = cached_source(sys.argv[1], sys.argv[2])
    print(f"{len(text)} characters of verified source")
