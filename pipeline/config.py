"""Loads settings from the .env file in the repo root.

Every key is read from the environment, never hardcoded, so the code can be
pushed to GitHub safely. Missing settings stop the program with a clear
message instead of silently falling back to fake data.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CASES_CSV = DATA_DIR / "cases.csv"
TRACES_DIR = DATA_DIR / "traces"   # raw `cast run` output, one .txt per tx
FRAMES_DIR = DATA_DIR / "frames"   # parsed call frames, one .json per tx

load_dotenv(REPO_ROOT / ".env")

RPC_ENV_BY_CHAIN = {"eth": "ETH_RPC_URL", "bsc": "BSC_RPC_URL"}


def require(name: str) -> str:
    """Return an environment variable or exit with instructions."""
    value = os.environ.get(name, "").strip()
    if not value or "PASTE_" in value:
        sys.exit(
            f"Missing setting {name}. Copy .env.example to .env in "
            f"{REPO_ROOT} and fill in {name}."
        )
    return value


def rpc_url(chain: str) -> str:
    chain = chain.lower()
    if chain not in RPC_ENV_BY_CHAIN:
        sys.exit(f"Unsupported chain '{chain}'. Supported: {list(RPC_ENV_BY_CHAIN)}")
    return require(RPC_ENV_BY_CHAIN[chain])


def optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None
