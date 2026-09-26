# Project status for the report-writing chat

Last updated: 2026-09-25. Written for the chat drafting the Overleaf report.
Everything here was measured from real runs in this repo. If a number is not
in this file or in `data/CHECKPOINT.md`, it has not been measured yet — do not
write it into the report.

## Where the pipeline stands

| Step | State |
|------|-------|
| 1. Rotate keys, clean old folders | **incomplete**: the Alchemy key in `.env` is still the one exposed in git history |
| 2. Install Foundry | done: `cast 1.8.3`, attestation-verified |
| 3. Checkpoint C01 + C16 against real `cast` output | done, passed |
| 4. Overleaf citation fixes (`latex/CHAPTER_FIXES.md`) | still open, done in Overleaf |
| 5. Fetch all 28 traces | done |
| 6. Annotation sheet (role + essential) | **LLM-drafted, awaiting human review** |
| 7. Classifier and `evaluate.py`, conditions C0-C5 | C0, C1 done; C2-C5 running |
| 8. Chapters 5 and 6 from results | Chapter 5 material generated; Chapter 6 has its finding |

The experiment now runs, but **no role accuracy figure exists yet and none can
exist until the annotation sheet is filled in by hand**. See "What is blocked".

## Step 6: the annotation is LLM-drafted and NOT yet reviewed

**This changes how the annotation must be described in the report.** Labelling
1,335 calls from a blank sheet was judged too slow, so the labels were drafted
automatically and will be corrected by the author rather than written from
scratch.

`data/annotation/sheet_draft.csv` holds a draft role and essential flag for
every one of the 1,335 calls, each row marked `annotator=llm-draft` and
`reviewed=no`. Distribution: 831 PREPARATORY, 262 TRIGGER, 242 EXTRACTION.
76 rows carry a `CHECK:` note where the drafting rules are least reliable.

How the draft was made, which is what the methodology section has to say:
the trigger calls were identified by reading all 28 traces; for 26 cases the
benchmark's own ground-truth function matched the trace, and two needed an
addition (C17's price-manipulating deposit, C18's setAuthorizationWithSig).
Every other call was then labelled by four written structural rules. The full
statement is the docstring of `pipeline/draft_annotations.py`.

**Consequences that must be disclosed, not hidden:**

- The annotation is **LLM-drafted, author-reviewed**, not independent human
  annotation. Say so plainly.
- **Cohen's kappa is not available.** There is no second independent human
  annotator. Report its absence as a limitation. Do not compute agreement
  between two model passes and call it inter-annotator reliability.
- `evaluate.py` treats a draft row as gold only once it is marked
  `reviewed=yes`. Unreviewed rows are scored separately and printed as
  "PROVISIONAL", because scoring a model against another model's labels
  measures agreement, not correctness.
- **A confound:** the draft's structural rules overlap with the C0 baseline's
  structural rules, so C0 agrees with the draft more than it deserves. Any C0
  number against draft labels is partly circular and is not C0's accuracy.

## The original blank sheet

`data/annotation/sheet.csv` has one row per call frame, 1,335 rows across 28
cases, with `role` and `essential` deliberately empty. `GUIDELINES.md` beside
it holds the written scheme, including the boundary rules that annotators
disagree on, and is the appendix material.

`second_annotator.csv` is the Cohen's kappa subset: one whole transaction per
category chosen with a fixed seed, 7 cases and 390 rows, 29.2% of all rows.
Whole transactions rather than scattered calls, because a call's purpose can
only be judged against the rest of the attack.

## Step 7: conditions, and what each may see

`pipeline/classify.py` implements C0 to C5, each adding exactly one thing.
Two design choices that belong in the methodology section:

- The victim's identity comes from the benchmark ground truth, so it is
  **withheld until C5**. C3 reveals only the attacker's account and the attack
  contract, both readable from the transaction itself. Revealing the victim
  earlier would leak the answer.
- C4's few-shot examples come from **dev cases only**; test cases never appear
  in a prompt.

Provider limits, measured rather than assumed: 7,000 input tokens per minute,
1,000 output tokens per minute, 1,000 requests per day. Two consequences that
must be reported as method, not hidden:

- **Long transactions are split into windows of at most 40 calls.** Every case
  goes through the same windowing code, so a small case simply produces one
  window and the procedure does not differ between cases. A condition-run is
  50 requests. The limitation to state: in a windowed case the model sees a
  slice of the call list, not the whole transaction at once.
- Argument and event text is clipped to the same width for every case, so a
  large transaction is not described more thinly than a small one.

### The binding constraint: 200,000 tokens per day

Measured, not assumed. The free Groq tier allows **200,000 tokens per day**,
alongside 7,000 input tokens/minute and 1,000 output tokens/minute.

One condition-run over 28 cases costs roughly 75,000-115,000 tokens. C1 used
72,647 and C2 used 112,426, which together exhausted the daily budget and is
why C2 stopped at 23 of 28 cases. **Roughly two condition-runs fit in a day.**

The full grid as planned, C1 to C5 at three runs each, is fifteen
condition-runs, so about 1.5 million tokens, or **eight days on the free
tier**. That is a real constraint on the experiment and the report should
either narrow the design or note that a paid tier was needed. Options, in the
order they cost least: drop to one run per condition and lose the run-agreement
metric; run fewer conditions; spread the work over days; or upgrade the tier.

### The central finding, and two metric corrections

Two things were reported wrongly earlier in this file and are corrected here.
Both corrections matter more than the numbers they replaced.

**Correction 1: `hit@any` was reported alone.** That flatters every condition,
because a model that calls half a transaction a TRIGGER hits the right call by
volume. Never write a hit@k number without precision and the trigger rate
beside it.

**Correction 2: an apparent "collapse on large traces" was a base-rate
artefact.** Precision and F1 do fall as transactions get bigger, but so does
the share of calls the benchmark marks as the vulnerable function: 23.1% in
transactions of 10 calls or fewer, 2.8% in those of 41 to 100. Precision falls
automatically when the target gets rarer. Once that is divided out, the
degradation disappears. **Do not claim the model gets worse on large traces.**

The metric that survives this is **lift over chance**: precision divided by the
rate a labeller would achieve by marking calls at random. 1.0 is chance.

### Trigger identification, all 28 cases

| Condition | hit@1 | hit@3 | Precision | Recall | F1 | Called TRIGGER | Benchmark marks | **Lift** |
|-----------|-------|-------|-----------|--------|-----|----------------|-----------------|----------|
| C0 rules  | 0/28 | 13/28 | 0.209 | 0.699 | **0.322** | 23.3% | 7.0% | **3.00** |
| C1 masked | 8/28 | 11/28 | 0.144 | 0.839 | 0.245 | 40.7% | 7.0% | 2.06 |
| C2 named  | 6/23 | 12/23 | 0.117 | 0.622 | 0.196 | 24.5% | 4.6% | 2.54 |

### Lift by transaction size: flat, not degrading

| Condition | tiny (<=10) | small (11-40) | medium (41-100) | large (>100) |
|-----------|-------------|---------------|-----------------|--------------|
| C0 rules  | 1.62 | 2.48 | 4.27 | 2.59 |
| C1 masked | 3.25 | 1.43 | 2.17 | 2.21 |
| C2 named  | 2.17 | 2.50 | 2.71 | 2.03 |

No trend with size in any condition. The story is a flat, modest edge over
chance everywhere, not a size-dependent failure.

### The ablation effect: names make the model selective

What each rung does to the model's own behaviour, over the 28 cases labelled
under every condition. This needs no ground truth: it is what the model chose
to say.

| Condition | PREPARATORY | TRIGGER | EXTRACTION | essential=yes |
|-----------|-------------|---------|------------|---------------|
| C0 rules  | 53.3% | 23.3% | 23.4% | 61.7% |
| C1 masked | 44.4% | **40.7%** | 14.9% | 61.5% |
| C2 named  | 57.4% | **25.6%** | 17.0% | 53.8% |

**Revealing contract and function names makes the model 15 points more
selective about TRIGGER**, from 40.7% to 25.6%. With structure alone it
over-fires badly; given names it becomes markedly more conservative and closer
to the benchmark's 7.0%, though still three to four times above it.

This is the ablation working as designed: one variable changed, one effect
attributable to it. It is the clearest positive result in the study so far and
should be reported alongside the negative one.

### What to write in Chapter 6

Three claims, all measured, all defensible:

1. **Every condition over-labels TRIGGER by three to six times.** The benchmark
   marks 7.0% of calls; the models mark 23% to 41%. Recall is high (0.62-0.84),
   precision is low (0.12-0.21). That is a wide net, not discrimination: the
   model finds the flawed call but cannot separate it from the setup that
   enabled it or the drain it caused.
2. **Performance is only modestly above chance**, 2.1x to 3.0x lift overall,
   and flat across transaction sizes.
3. **The rule baseline is not beaten.** C0 has the best F1 (0.322) and the best
   lift (3.00) of the three conditions measured so far. Report this plainly.

That is a negative result. Report it as the finding, with the mechanism, rather
than hunting for a positive one. A study that measures carefully enough to
catch its own base-rate artefact and to find that its baseline wins is a
stronger piece of work than one that reports an unexamined accuracy figure.

### A contrast for Chapter 5

On C06 (Seneca, 3 calls) condition C1 labels exactly one call TRIGGER and
matches the benchmark exactly, while C0 labels two of three. Use it to show what
success looks like, but do not generalise from it: the lift table shows tiny
transactions are not systematically easier once the base rate is accounted for.
`data/case_studies/` holds the generated material.

## What is blocked, and on what

| Blocked | Needs |
|---------|-------|
| Accuracy, macro-F1, per-role P/R, confusion matrix, essential P/R | the drafted rows reviewed and marked reviewed=yes |
| Cohen's kappa | **dropped**: no second independent human annotator |
| Condition C4 | the 7 dev cases reviewed, to build few-shot examples |
| Condition C5 | now unblocked: the Etherscan key is set |

`evaluate.py` reports each of these as unavailable rather than estimating it.
Chapter 6 cannot present role accuracy until the annotation exists. Chapter 5
case studies can be written now from the traces and the predictions.

## The trace corpus: what you may cite

All 28 cases replay and parse. Full per-case table in `data/CHECKPOINT.md`.

- **1,335 call frames** across 28 transactions.
- Frames per transaction: min 3, median 35, max 151 (C16 Euler).
- Max depth per transaction: min 2, median 4.5, max 82 (C24 Game).
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

3. **Withdraw the parser comparison. Do not claim anything about
   FaultSeeker's parser.** Two earlier claims were wrong and must come out of
   the notes and the report:

   - *"FaultSeeker's parser attributes depth by counting `|` characters and
     misplaces calls under a parent's last child."* The failure does not occur
     in real cast output: cast closes every frame with its own return line, so
     a call is never drawn as a last child. Measured over all 28 traces, 0 of
     1307 non-root calls carry the last-child marker, and column depth exceeds
     the `|` count by exactly 1 for all 1307. The two rules are equivalent up
     to a constant offset on this corpus.
   - *"FaultSeeker's approach cannot parse contract-creation transactions."*
     That was a bug in **this** project's parser, now fixed, not a property of
     theirs.

   The reason neither can be asserted: no copy of FaultSeeker's parser exists
   in this repo. `faultseeker/faultseeker.py` in git history is an early
   prototype of this project and does not parse call traces at all; it builds
   a two-level structure from the receipt and never sees internal calls. A
   real comparison needs github.com/kairanskrr/FaultSeeker run on these
   traces, which has not been done.

   What survives, and is measured: C03 and C26 are contract-creation
   transactions (`tx.to = null`, the attack runs in the constructor, the trace
   root is a CREATE node), exactly 2 of 28, verified against the chain. A
   parser that accepts only a call as the root yields zero frames on them and
   fails silently. Write that as a parser-design observation about handling
   creation-rooted traces, attributed to nobody.

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

**The Alchemy key currently in `.env` is already public.** It is committed in
this repo's own history at `fd912b4`, in `faultseeker/faultseeker.py`, as a
commented-out URL. Deleting that file did not remove it: the blob is still
reachable on GitHub. The key is byte-identical to the one in `.env` today,
confirmed by hashing both. It must be rotated at Alchemy, not just removed
from the file. The Groq key in that same commit is also public, but the
current `.env` Groq key is different, so that one was already rotated.

Separately, an RPC provider returned 429 during the batch fetch and the error
message contained the full Alchemy URL, printing the key to the terminal. The
code now redacts URLs from every error message and retries 429/5xx with
backoff.

`.env` itself is gitignored and no key has been committed by the current
pipeline. The exposure is entirely historical, and rotation is the only fix.

## Where to read the detail

- `data/CHECKPOINT.md` — full per-case table, fidelity evidence, parser audit.
- `data/frames/summary.csv` — one row per case, machine-readable.
- `data/frames/<txhash>.json` — parsed frames plus on-chain facts per case.
- `data/traces/<txhash>.txt` — raw `cast run` output per case.
- `latex/CHAPTER_FIXES.md` — the citation fixes still to apply in Overleaf.
