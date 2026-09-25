# Trace corpus: what was fetched, and what is verified

Run on 2026-09-25 with Foundry `cast 1.8.3` (commit `cae51ad458`, build
2026-09-15), Python 3.11.0, Windows 11, Git Bash. Archive RPC: Alchemy
(`eth-mainnet.g.alchemy.com`, `bnb-mainnet.g.alchemy.com`), free tier.

Every number below was measured from a real replay. Nothing here is estimated
or carried over from the FaultSeeker paper.

## Headline

- All **28/28** cases replayed and parsed: **1335 call frames** in total.
- **25/28** replays are verified faithful: the replayed gas equals the
  on-chain receipt gas exactly.
- **3/28** are not verified: C03, C26, C27 (all BSC). See below.
- The ground-truth vulnerable function is located in the trace for **28/28** cases.

## Replay fidelity

`cast run --quick` is tried first; if the replayed gas or status differs from
the receipt, the block is replayed in full automatically. 4 cases needed the
full replay (C03, C22, C26, C27).

### The three unverified cases

| Case | Chain | Receipt gas | Replayed gas | Shortfall |
|------|-------|-------------|--------------|-----------|
| C03 | bsc | 913,452 | 897,010 | 16,442 |
| C26 | bsc | 1,012,928 | 838,904 | 174,024 |
| C27 | bsc | 582,128 | 403,528 | 178,600 |

In all three the replay executes cleanly: no reverted calls, the expected
contracts and functions appear, and the ground-truth function is found. Only
the gas total is short. What has been ruled out:

- **EVM version.** C27 was replayed with `--evm-version` berlin, london, paris,
  shanghai and cancun. All five produce exactly 403,528 gas, so the difference
  is not the opcode gas schedule.
- **Skipped preceding transactions.** All three already use the full-block
  replay, not `--quick`.
- **A failing or diverging call path.** The traces contain no reverts and end
  in `Transaction successfully executed`.

What could not be checked: `debug_traceTransaction` and `trace_transaction`
are both blocked on the free Alchemy tier, so the node's own gas accounting
could not be compared against cast's. The cause is therefore **undetermined**.
The fourth BSC case, C07, replays exactly, so this is not a blanket BSC
problem.

**These three must not be used as verified traces until the mismatch is
explained.** `fetch_traces.py` writes them with `replay_faithful=false`,
prints a warning naming them, and exits non-zero.

## Parser audit

Call-like lines were counted directly from each raw trace with an independent
regex, not the parser's own logic, and compared with the frames emitted:

| Cases | Call lines in raw traces | Frames parsed | Missed | Spurious | Structural errors |
|-------|--------------------------|---------------|--------|----------|-------------------|
| 28 | 1335 | 1335 | 0 | 0 | 0 |

Structural checks applied to all 1335 frames: exactly the root frame has no
parent, every child's depth is its parent's depth plus one, indices are
sequential in execution order, and each frame's `n_children` equals the number
of frames naming it as parent.

### Parser bug found and fixed: contract-creation transactions

C03 (Melo) and C26 (BUNN) are **contract-creation transactions**: `tx.to` is
null and the attack runs inside the deployed contract's constructor, so the
root node of the trace is a `new <unknown>@0x...` node rather than a call.
The parser only recognised a *call* as a possible root, so it never set the
root column, skipped every subsequent line, and raised "No call trace found"
on both cases.

All 28 transactions were checked against the chain: exactly C03 and C26 are
creation-rooted. The fix lets a CREATE node open the trace, and
`python pipeline/trace_parser.py --selftest` now covers it with a
creation-rooted fixture alongside the original one.

This is worth reporting in Chapter 3 next to the existing depth-attribution
point: both are cases where a trace parser silently produces nothing, or the
wrong structure, rather than failing loudly.

### API keys were being printed on error

A throttled RPC call raised a `requests` exception whose message contains the
full URL, and the Alchemy key sits in that URL, so the key was printed to the
terminal. `rpc_call` now retries 429 and 5xx responses with exponential
backoff and passes every error message through `redact()`, which strips the
path from any URL before it can be printed or logged. `cast`'s own stderr is
redacted the same way, since the RPC URL is passed to it on the command line.

## Our frame counts differ from the benchmark's `benchmark_calls`

| Case | Our calls | Our events | Our max depth (0-indexed) | benchmark_calls | benchmark_max_depth |
|------|-----------|-----------|---------------------------|-----------------|---------------------|
| C01 | 7   | 3  | 2  | 10  | 4  |
| C16 | 151 | 56 | 11 | 258 | 13 |

Depth is explained for both: the benchmark counts depth 1-indexed and counts
emitted events as one further level, so its depth equals ours plus two.

The call count is explained for C01 only: 7 calls + 3 events = 10, i.e. the
benchmark counts emitted events as call nodes. C16 does not fit that rule:
151 calls + 56 events = 207, against a benchmark figure of 258. Since our
replay reproduces the receipt gas exactly, the executed calls are not in
question; the residual is a difference in what the benchmark's tracer counted
as a node. State it as a measured difference in Chapter 3; do not reconcile it
by assumption.

## Notes for Chapters 3 and 4

The Euler transaction is
`0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d`,
confirmed on Ethereum mainnet at block 16,817,996, gas 1,949,994. The hash
ending `965cc70` currently in the report is wrong.

C24 (Game) is worth considering as a case study: it reaches depth 82 through a
repeated `makeBid` pattern, by far the deepest trace in the corpus, and its
ground-truth function matches 42 separate frames. C16 (Euler) is the widest at
151 frames.

## Per-case results

| Case | Name | Category | Split | Chain | Frames | Max depth | Replay | Ground truth found at |
|------|------|----------|-------|-------|--------|-----------|--------|-----------------------|
| C01 | Templedao | access_control | dev | eth | 7 | 2 | verified | `migrateStake` @ 3 |
| C02 | Paraswap | access_control | test | eth | 12 | 4 | verified | `transferfrom` @ 7 |
| C03 | Melo | access_control | test | bsc | 15 | 3 | **MISMATCH** | `mint` @ 3 |
| C04 | Uerii Token | access_control | test | eth | 31 | 5 | verified | `mint` @ 2;3 |
| C05 | CowSwap | arbitrary_external_call | dev | eth | 7 | 2 | verified | `envelope` @ 4 |
| C06 | Seneca | arbitrary_external_call | test | eth | 3 | 2 | verified | `performOperations` @ 2 |
| C07 | ChaingeFinance | arbitrary_external_call | test | bsc | 11 | 2 | verified | `swap` @ 4 |
| C08 | Dexible | arbitrary_external_call | test | eth | 38 | 6 | verified | `fill;selfSwap` @ 8;9;10;11 |
| C09 | Umbrella Network | arithmetic | dev | eth | 4 | 3 | verified | `withdraw` @ 3 |
| C10 | Pandora | arithmetic | test | eth | 18 | 2 | verified | `transferFrom` @ 3;8 |
| C11 | MetaLend | arithmetic | test | eth | 128 | 13 | verified | `redeemUnderlying` @ 75 |
| C12 | Balancer | arithmetic | test | eth | 140 | 10 | verified | `onSwap` @ 22 (+7 more) |
| C13 | HedgeyFinance | business_logic | dev | eth | 5 | 2 | verified | `transferFrom` @ 4;5 |
| C14 | WIFCOIN_ETH | business_logic | test | eth | 19 | 3 | verified | `stake` @ 15 |
| C15 | DAppSocial | business_logic | test | eth | 46 | 4 | verified | `LockTokens` @ 8;25 |
| C16 | EulerFinance | business_logic | test | eth | 151 | 11 | verified | `donateToReserves` @ 64 |
| C17 | Formation.Fi | price_oracle_manipulation | dev | eth | 21 | 4 | verified | `swapIn` @ 12 |
| C18 | MorphoBlue | price_oracle_manipulation | test | eth | 32 | 6 | verified | `borrow` @ 22 |
| C19 | VINU | price_oracle_manipulation | test | eth | 53 | 4 | verified | `addLiquidityETH` @ 13;19;25;31 |
| C20 | Kashi | price_oracle_manipulation | test | eth | 80 | 8 | verified | `withdraw` @ 52;54 |
| C21 | JAY | reentrancy | dev | eth | 38 | 6 | verified | `buyJay` @ 9;11;22;24 |
| C22 | Orion Protocol | reentrancy | test | eth | 94 | 12 | verified | `doSwapThroughOrionPool` @ 33 |
| C23 | DFXFinance | reentrancy | test | eth | 94 | 7 | verified | `flash;deposit` @ 24;38 |
| C24 | Game | reentrancy | test | eth | 127 | 82 | verified | `makeBid` @ 2 (+41 more) |
| C25 | TINU | token_specific | dev | eth | 39 | 5 | verified | `deliver` @ 21;28 |
| C26 | BUNN | token_specific | test | bsc | 26 | 4 | **MISMATCH** | `deliver` @ 10;18 |
| C27 | FDP | token_specific | test | bsc | 38 | 5 | **MISMATCH** | `deliver` @ 21 |
| C28 | NUM | token_specific | test | eth | 58 | 7 | verified | `anySwapOutUnderlyingWithPermit` @ 8 |

## Reproduce

    python pipeline/trace_parser.py --selftest
    python pipeline/fetch_traces.py --all
