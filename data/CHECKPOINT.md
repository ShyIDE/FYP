# Checkpoint: parser verified against real `cast run` output

Run on 2026-09-25 with Foundry `cast 1.8.3` (commit `cae51ad458`, build
2026-09-15), Python 3.11.0, Windows 11, Git Bash. Archive RPC: Alchemy
(`eth-mainnet.g.alchemy.com`).

Cases C01 (Templedao, smallest) and C16 (EulerFinance, largest) were replayed
end to end. Everything below was measured, not estimated.

## Replay fidelity

Both cases replayed with `cast run --quick`; no full-block replay was needed.

| Case | Block | Receipt gas | Replay gas | Status | Faithful |
|------|-------|-------------|-----------|--------|----------|
| C01 Templedao   | 15,725,067 | 173,509   | 173,509   | success | yes (exact) |
| C16 EulerFinance| 16,817,996 | 1,949,994 | 1,949,994 | success | yes (exact) |

Gas matches the on-chain receipt exactly in both cases, so the replayed
execution is the real transaction, not an approximation.

The Euler transaction hash used here is
`0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d`
(confirmed present on Ethereum mainnet at block 16,817,996). The hash
`...965cc70` used in Chapters 3-4 of the current report is wrong.

## Ground-truth function located in the trace

| Case | Ground-truth function | Found at frame |
|------|----------------------|----------------|
| C01 | `migrateStake`     | 3  |
| C16 | `donateToReserves` | 64 |

## Parser audit

For each case, call-like lines were counted directly from the raw trace text
with an independent regex (not the parser's own logic) and compared with the
frames the parser emitted:

| Case | Call lines in raw trace | Frames parsed | Missed | Spurious |
|------|------------------------|---------------|--------|----------|
| C01 | 7   | 7   | 0 | 0 |
| C16 | 151 | 151 | 0 | 0 |

Structural invariants hold for every frame in both cases: exactly the root
frame has no parent, every child's depth is its parent's depth plus one,
indices are sequential in execution order, and each frame's `n_children`
equals the number of frames naming it as parent.

## Our frame counts differ from the benchmark's `benchmark_calls`

| Case | Our calls | Our events | Our max depth (0-indexed) | benchmark_calls | benchmark_max_depth |
|------|-----------|-----------|---------------------------|-----------------|---------------------|
| C01 | 7   | 3  | 2  | 10  | 4  |
| C16 | 151 | 56 | 11 | 258 | 13 |

Depth is explained for both cases: the benchmark counts depth 1-indexed and
counts emitted events as one further level, so its depth equals ours plus two.

The call count is explained for C01 only: 7 calls + 3 events = 10, i.e. the
benchmark counts emitted events as call nodes. C16 does not fit that rule:
151 calls + 56 events = 207, against a benchmark figure of 258 (51 more).
Since our replay reproduces the receipt gas exactly, the executed calls are
not in question; the residual is a difference in what the benchmark's tracer
counted as a node, and it was not produced by `cast`. This should be stated as
a measured difference in Chapter 3 rather than reconciled by assumption.

## Reproduce

    python pipeline/trace_parser.py --selftest
    python pipeline/fetch_traces.py --case C01
    python pipeline/fetch_traces.py --case C16
