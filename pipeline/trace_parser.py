"""Parse the text trace printed by Foundry's `cast run` into call frames.

A trace looks like this (one root call, children indented under it):

    Traces:
      [285463] 0xAttacker::attack()
        ├─ [2530] USDT::balanceOf(0x...) [staticcall]
        │   └─ ← [Return] 1000
        ├─ [45000] Pool::flashLoan(...)
        │   ├─ emit Transfer(from: ..., to: ..., value: ...)
        │   └─ ← [Stop]
        └─ ← [Stop]

Depth is taken from the column where the branch marker (├─ or └─) sits.
Counting the "│" characters instead (as FaultSeeker's parser does) gives the
wrong depth for anything nested under a parent's *last* child, because those
lines are indented with spaces rather than "│".

Run `python pipeline/trace_parser.py --selftest` to check the parser.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field

ANSI = re.compile(r"\x1b\[[0-9;]*m")
LINE = re.compile(r"^(?P<prefix>[ \t│]*)(?P<marker>[├└]─\s?)?(?P<content>.*)$")
CALL = re.compile(
    r"^\[(?P<gas>\d+)\]\s+(?P<target>\S+?)::(?P<fn>[^({\s]+)"
    r"(?:\{(?P<opts>[^}]*)\})?\((?P<args>.*)\)"
    r"(?:\s+\[(?P<ctype>staticcall|delegatecall|callcode|call)\])?\s*$"
)
CREATE = re.compile(r"^\[(?P<gas>\d+)\]\s+→\s+new\s+(?P<name>.*?)@(?P<addr>0x[0-9a-fA-F]{40})")
RETURN = re.compile(r"^←\s*(?:\[(?P<kind>\w+)\])?\s*(?P<data>.*)$")
EMIT = re.compile(r"^emit\s+(?P<body>.+)$")
GAS_USED = re.compile(r"Gas used:\s*(\d+)")
HEX_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
RAW_SELECTOR = re.compile(r"^(0x)?[0-9a-fA-F]{8}$")

MAX_ARGS = 300
MAX_RET = 200


@dataclass
class Frame:
    index: int                 # execution order (1 = outermost call)
    depth: int                 # 0 = the transaction's top-level call
    parent: int | None         # index of the calling frame
    kind: str                  # CALL, STATICCALL, DELEGATECALL, CALLCODE, CREATE
    target: str                # label or address as printed by cast
    target_address: str | None
    function: str
    decoded: bool              # False if cast only knew the 4-byte selector
    args: str
    value: str | None          # ETH sent with the call, if any
    gas: int
    outcome: str | None = None # Return, Stop, Revert, ...
    return_data: str | None = None
    events: list[str] = field(default_factory=list)
    n_children: int = 0
    line_no: int = 0


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def parse_trace(text: str) -> dict:
    """Return {"frames": [...], "cast_gas_used": int|None, "cast_status": str}."""
    lines = [ANSI.sub("", ln.rstrip("\r")) for ln in text.split("\n")]
    frames: list[Frame] = []
    open_at: dict[int, Frame] = {}   # depth -> frame currently open at that depth
    root_col: int | None = None
    in_traces = False
    last_event: tuple[Frame, int] | None = None

    for line_no, raw in enumerate(lines, 1):
        if raw.strip() == "Traces:":
            in_traces = True
            continue
        m = LINE.match(raw)
        if not m or not m.group("content").strip():
            continue
        prefix, marker, content = m.group("prefix"), m.group("marker"), m.group("content").strip()

        if marker is None:
            # A root call or root contract creation (no branch marker), or a
            # continuation line of an undecoded event ("topic 1: ...",
            # "data: ..."), or cast chatter.
            call = CALL.match(content)
            create = CREATE.match(content) if not call else None
            if (call or create) and root_col is None and (in_traces or not frames):
                root_col = len(prefix)
                # A contract-creation transaction (tx.to is null) puts a
                # "new X@0x..." node at the root: the attacker deploys the
                # attack contract and its constructor runs the exploit.
                f = _make_root(call, create, line_no)
                frames.append(f)
                open_at = {0: f}
                continue
            if last_event and re.match(r"^(topic \d+|data):", content):
                owner, i = last_event
                owner.events[i] = _clip(owner.events[i] + " " + content, MAX_ARGS)
            continue

        if root_col is None:
            continue
        depth = (len(prefix) - root_col - 2) // 4 + 1
        owner = open_at.get(depth - 1)
        if owner is None:
            raise ValueError(f"line {line_no}: depth {depth} has no parent frame:\n{raw}")

        call = CALL.match(content)
        create = CREATE.match(content) if not call else None
        if call or create:
            idx = len(frames) + 1
            if call:
                f = _make_call(call, idx, depth, owner.index, line_no)
            else:
                f = _make_create(create, idx, depth, owner.index, line_no)
            owner.n_children += 1
            frames.append(f)
            open_at = {d: fr for d, fr in open_at.items() if d < depth}
            open_at[depth] = f
            last_event = None
            continue

        ret = RETURN.match(content)
        if ret:
            owner.outcome = ret["kind"] or "Return"
            owner.return_data = _clip(ret["data"], MAX_RET) or None
            last_event = None
            continue

        emit = EMIT.match(content)
        if emit:
            owner.events.append(_clip(emit["body"], MAX_ARGS))
            last_event = (owner, len(owner.events) - 1)
            continue

    if not frames:
        raise ValueError("No call trace found. Check the raw cast output for an error message.")

    gas = GAS_USED.findall(text)
    status = "failed" if re.search(r"Transaction failed", text, re.I) else "success"
    return {
        "frames": [asdict(f) for f in frames],
        "cast_gas_used": int(gas[-1]) if gas else None,
        "cast_status": status,
    }


def _make_create(m: re.Match, idx: int, depth: int, parent: int | None, line_no: int) -> Frame:
    return Frame(idx, depth, parent, "CREATE", m["name"], m["addr"],
                 f"new {m['name']}", True, "", None, int(m["gas"]), line_no=line_no)


def _make_root(call: re.Match | None, create: re.Match | None, line_no: int) -> Frame:
    if call:
        return _make_call(call, 1, 0, None, line_no)
    return _make_create(create, 1, 0, None, line_no)


def _make_call(m: re.Match, idx: int, depth: int, parent: int | None, line_no: int) -> Frame:
    target, fn = m["target"], m["fn"]
    value = None
    if m["opts"]:
        v = re.search(r"value:\s*([^,}]+)", m["opts"])
        value = v.group(1).strip() if v else None
    return Frame(
        index=idx, depth=depth, parent=parent,
        kind=(m["ctype"] or "call").upper(),
        target=target,
        target_address=target if HEX_ADDR.match(target) else None,
        function=fn,
        decoded=not RAW_SELECTOR.match(fn),
        args=_clip(m["args"], MAX_ARGS),
        value=value,
        gas=int(m["gas"]),
        line_no=line_no,
    )


# ---------------------------------------------------------------- self-test
_FIXTURE = """Executing previous transactions from the block.
Traces:
  [285463] 0xAAAA000000000000000000000000000000000001::attack()
    ├─ [2530] USDT::balanceOf(0xAAAA000000000000000000000000000000000001) [staticcall]
    │   └─ ← [Return] 1000
    ├─ [45000] Pool::flashLoan(0xAAAA000000000000000000000000000000000001, 5000)
    │   ├─ [3000] USDT::transfer(0xAAAA000000000000000000000000000000000001, 5000)
    │   │   ├─ emit Transfer(from: Pool, to: 0xAAAA000000000000000000000000000000000001, value: 5000)
    │   │   └─ ← [Return] true
    │   ├─ [20000] 0xAAAA000000000000000000000000000000000001::onFlashLoan(5000)
    │   │   ├─ [9000] Proxy::donateToReserves(1, 2)
    │   │   │   ├─ [7000] Impl::donateToReserves(1, 2) [delegatecall]
    │   │   │   │   └─ ← [Stop]
    │   │   │   └─ ← [Stop]
    │   │   └─ ← [Return]
    │   └─ ← [Stop]
    ├─ [1200] 0xBBBB000000000000000000000000000000000002::925d400c(00000000000000000001)
    │   └─ ← [Revert] revert: not owner
    ├─ [30000] → new Helper@0xCCCC000000000000000000000000000000000003
    │   └─ ← [Return] 512 bytes of code
    └─ [8000] Router::swap{value: 1000000000000000000}(1, 2)
        ├─ emit topic 0: 0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef
        │        topic 1: 0x0000000000000000000000000000000000000000000000000000000000000001
        │           data: 0x05
        ├─ [700] WETH::deposit{value: 5}()
        │   └─ ← [Stop]
        └─ ← [Return] 42


Transaction successfully executed.
Gas used: 312480
"""


# A contract-creation transaction (tx.to is null): the root node is a CREATE,
# not a call. Cases C03 (Melo) and C26 (BUNN) in the benchmark look like this.
_FIXTURE_CREATE_ROOT = """Traces:
  [823108] → new <unknown>@0x4985DB6Fa42F6a30Ea7D20CB19591A0552C67238
    ├─ [2496] 0x9A1aEF8C9ADA4224aD774aFdaC07C24955C92a54::balanceOf(0x6a8C4448763C08aDEb80ADEbF7A29b9477Fa0628) [staticcall]
    │   └─ ← [Return] 2939318004043799027926976
    ├─ [32440] 0x9A1aEF8C9ADA4224aD774aFdaC07C24955C92a54::mint(0x4985DB6Fa42F6a30Ea7D20CB19591A0552C67238, 146965900202189951396348800, "")
    │   ├─ emit Transfer(from: 0x0000000000000000000000000000000000000000, to: 0x4985DB6Fa42F6a30Ea7D20CB19591A0552C67238, amount: 1)
    │   └─ ← [Return] 0x01
    └─ ← [Return] 1337 bytes of code


Transaction successfully executed.
Gas used: 913452
"""


def _selftest_create_root() -> None:
    out = parse_trace(_FIXTURE_CREATE_ROOT)
    frames = out["frames"]
    got = [(f["index"], f["depth"], f["parent"], f["kind"], f["function"]) for f in frames]
    expected = [
        (1, 0, None, "CREATE", "new <unknown>"),
        (2, 1, 1, "STATICCALL", "balanceOf"),
        (3, 1, 1, "CALL", "mint"),
    ]
    assert got == expected, f"\nexpected {expected}\n     got {got}"
    root = frames[0]
    assert root["target_address"] == "0x4985DB6Fa42F6a30Ea7D20CB19591A0552C67238"
    assert root["n_children"] == 2
    assert frames[2]["events"] and frames[2]["events"][0].startswith("Transfer(")
    assert out["cast_gas_used"] == 913452 and out["cast_status"] == "success"
    print("trace_parser create-root self-test passed: 3 frames, CREATE root parsed.")


def _selftest() -> None:
    out = parse_trace(_FIXTURE)
    fr = {f["index"]: f for f in out["frames"]}
    got = [(f["index"], f["depth"], f["parent"], f["kind"], f["function"]) for f in out["frames"]]
    expected = [
        (1, 0, None, "CALL", "attack"),
        (2, 1, 1, "STATICCALL", "balanceOf"),
        (3, 1, 1, "CALL", "flashLoan"),
        (4, 2, 3, "CALL", "transfer"),
        (5, 2, 3, "CALL", "onFlashLoan"),
        (6, 3, 5, "CALL", "donateToReserves"),
        (7, 4, 6, "DELEGATECALL", "donateToReserves"),
        (8, 1, 1, "CALL", "925d400c"),
        (9, 1, 1, "CREATE", "new Helper"),
        (10, 1, 1, "CALL", "swap"),
        (11, 2, 10, "CALL", "deposit"),   # nested under a LAST child: FaultSeeker's parser gets depth 1
    ]
    assert got == expected, f"\nexpected {expected}\n     got {got}"
    assert fr[2]["outcome"] == "Return" and fr[2]["return_data"] == "1000"
    assert fr[4]["events"] and fr[4]["events"][0].startswith("Transfer(")
    assert fr[8]["decoded"] is False and fr[8]["outcome"] == "Revert"
    assert fr[10]["value"] == "1000000000000000000" and fr[11]["value"] == "5"
    assert "topic 1:" in fr[10]["events"][0] and "data: 0x05" in fr[10]["events"][0]
    assert fr[1]["n_children"] == 5 and fr[1]["target_address"]
    assert out["cast_gas_used"] == 312480 and out["cast_status"] == "success"
    print("trace_parser self-test passed: 11 frames, depths and parents correct.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        _selftest_create_root()
    elif len(sys.argv) == 2:
        with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
            print(json.dumps(parse_trace(fh.read()), indent=2, ensure_ascii=False))
    else:
        print("usage: python pipeline/trace_parser.py --selftest | <raw_trace.txt>")
