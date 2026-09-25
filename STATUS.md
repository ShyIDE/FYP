# Project status for the report-writing chat

Last updated: 2026-09-25. Written for the chat drafting the Overleaf report.
Everything here was measured from real runs in this repo. If a number is not
in this file or in `data/CHECKPOINT.md`, it has not been measured yet — do not
write it into the report.

## Where the pipeline stands

| Step | State |
|------|-------|
| 1. Rotate keys, clean old folders | done for the repo; see the security note below |
| 2. Install Foundry | done: `cast 1.8.3`, attestation-verified |
| 3. Checkpoint C01 + C16 against real `cast` output | done, passed |
| 4. Overleaf citation fixes (`latex/CHAPTER_FIXES.md`) | still open, done in Overleaf |
| 5. Fetch all 28 traces | done |
| 6. Annotation sheet (role + essential) | not started, next |
| 7. Classifier and `evaluate.py`, conditions C0-C5 | not started |
| 8. Chapters 5 and 6 from results | blocked on 6 and 7 |

No LLM has been run yet. There are no classification results, no accuracy
numbers, no confusion matrices and no cost figures. Chapters 5 and 6 cannot be
written yet.

## The trace corpus: what you may cite

All 28 cases replay and parse. Full per-case table in `data/CHECKPOINT.md`.

- **1,335 call frames** across 28 transactions.
- Frames per transaction: min 3, median 35, max 151 (C16 Euler).
- Max depth per transaction: min 2, median 4, max 82 (C24 Game).
- Composition: 511 staticcalls, 219 delegatecalls, 1,140 emitted events,
  68 frames where `cast` knew only the 4-byte selector.
- The ground-truth vulnerable function is located in the trace for **28/28**
  cases.

### Replay fidelity — this is the important caveat

A replay counts as verified only when the replayed gas equals the on-chain
receipt gas exactly.

- **25 of 28 verified** (1,256 frames).
- **3 not verified: C03 (Melo), C26 (BUNN), C27 (FDP)** — all BSC. They
  execute cleanly and find their ground-truth function, but the gas total
  falls short of the receipt by 16,442 / 174,024 / 178,600 respectively.
  Cause undetermined. Ruled out: the EVM gas schedule (C27 gives identical
  gas under berlin, london, paris, shanghai and cancun) and skipped preceding
  transactions (all three use full-block replay). Could not be checked:
  `debug_traceTransaction` is blocked on the free Alchemy tier. C07, the
  fourth BSC case, replays exactly, so it is not a blanket BSC problem.

**How to write this:** report the corpus as 28 cases fetched, 25 verified
faithful, and state the three exclusions and the reason plainly. Do not
quietly drop them and do not present 28 as if all were verified. If the
annotation ends up running on the verified 25, say so and give the split.

Useful consequence: **all 7 dev cases are verified.** The 3 unverified are all
in the test split. Few-shot prompting from dev cases is therefore unaffected.

## Corrections this run forces in the existing chapters

1. **Euler hash.** The real transaction is
   `0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d`,
   Ethereum mainnet block 16,817,996, gas 1,949,994, 151 frames, max depth 11,
   `donateToReserves` at frame 64. The hash ending `965cc70` in Chapters 3
   and 4 is wrong and every figure derived from it must go.

2. **Chapter 3 Figure 3.2 (category percentages) was estimated and is wrong
   in shape, not just in value.** The dataset is exactly balanced: 7
   categories, 4 cases each, 14.3% each. access_control,
   arbitrary_external_call, arithmetic, business_logic,
   price_oracle_manipulation, reentrancy, token_specific. A varying-percentage
   chart misrepresents the benchmark. Frames per category, measured:
   reentrancy 353, arithmetic 290, business_logic 221,
   price_oracle_manipulation 186, token_specific 161, access_control 65,
   arbitrary_external_call 59.

3. **The parser contribution in Chapter 3 now has two findings, not one.**
   The existing point stands: FaultSeeker's parser attributes depth by
   counting `|` characters, which misplaces any call nested under a parent's
   last child. The new one: their approach also cannot parse
   **contract-creation transactions**. C03 and C26 have `tx.to = null`, so the
   attack runs inside the deployed contract's constructor and the trace root
   is a CREATE node rather than a call. A parser that only accepts a call as
   the root produces *zero frames* and silently yields nothing. Exactly 2 of
   the 28 cases are creation-rooted, verified against the chain. Both findings
   share a theme worth stating: a trace parser that fails silently is worse
   than one that fails loudly.

4. **Frame counts do not match the benchmark's `benchmark_calls`, and this is
   a real measured difference, not an error to explain away.** The benchmark
   counts emitted events as call nodes and counts depth 1-indexed, which fully
   explains the depth column and explains C01's count (7 calls + 3 events =
   10). It does not explain C16: 151 calls + 56 events = 207 against their
   258. Our replay reproduces Euler's receipt gas exactly, so the executed
   calls are not in doubt. Report the discrepancy; do not invent a
   reconciliation.

## Still not true, still do not write it

- Do not call the system FAULTSEEKER and do not claim it is first of its kind.
  This project extends FaultSeeker (Sun et al., ASE 2025).
- No multi-agent consensus, no fine-tuning, no released dataset. Chapter 1 is
  rewritten last, against what was actually delivered.
- No model is trained. The experimental variable is the prompting condition.

## Security note

An RPC provider returned 429 during the batch fetch and the error message
contained the full Alchemy URL, so the API key was printed to the terminal.
The code now redacts URLs from every error message and retries 429/5xx with
backoff. The key was never committed. Brandon has been told to rotate it.
Nothing in this repo contains a key; `.env` is gitignored.

## Where to read the detail

- `data/CHECKPOINT.md` — full per-case table, fidelity evidence, parser audit.
- `data/frames/summary.csv` — one row per case, machine-readable.
- `data/frames/<txhash>.json` — parsed frames plus on-chain facts per case.
- `data/traces/<txhash>.txt` — raw `cast run` output per case.
- `latex/CHAPTER_FIXES.md` — the citation fixes still to apply in Overleaf.
