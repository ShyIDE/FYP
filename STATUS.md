# Project status

Last updated: 2026-09-28. The current state of the pipeline, and what the
measured results do and do not support.
Everything here was measured from real runs in this repo. If a number is not
in this file or in `data/CHECKPOINT.md`, it has not been measured yet — do not
write it into the report.

## Where the pipeline stands

| Step | State |
|------|-------|
| 1. Rotate keys, clean old folders | Groq rotated; Alchemy deliberately not rotated (see security note) |
| 2. Install Foundry | done: `cast 1.8.3`, attestation-verified |
| 3. Checkpoint C01 + C16 against real `cast` output | done, passed |
| 4. Overleaf citation fixes (`latex/CHAPTER_FIXES.md`) | still open, done in Overleaf |
| 5. Fetch all 28 traces | done |
| 6. Annotation sheet (role + essential) | drafted; **76 flagged rows reviewed by the author** |
| 7. Classifier and `evaluate.py`, conditions C0-C5 | **complete**: C0-C4 all 28 cases, C5 26 of 28 |
| 8. Chapters 5 and 6 from results | ready to write: results final, case studies generated |

All experiments are finished. Three-role accuracy now exists **for the 76 reviewed
calls only**. See "Three-role accuracy on the reviewed subset" below and
`data/predictions/RESULTS.md`.

### Three-role accuracy on the reviewed subset

The author reviewed and confirmed all 76 flagged rows. Accuracy on them, with
every condition scored on the 63 reviewed calls they all cover (C5 has no run
for C15), is 0.25 (C0), 0.38 (C1), 0.29 (C2), 0.41 (C3), 0.37 (C4) and
0.52 (C5).

How to write this up:

- **Report it as accuracy on the flagged subset, never as overall accuracy.**
  These are the 76 hardest calls, drawn from only 9 transactions.
- **Do not rank conditions on it.** The ordering is not monotonic, and 95%
  intervals resampled by case are wide (roughly ±0.2) and overlap heavily.
- The one safe observation is that C5, with the victim's source, scores highest
  on the calls the rules found hardest. That fits the main finding that context
  helps, but it is not established on its own.
- Do not put C5's all-reviewed figure (0.524 on 63 calls) in a table next to the
  others' 76-call figures. Use the shared-subset table in `RESULTS.md`.

## Step 6: the annotation is LLM-drafted and NOT yet reviewed

**This changes how the annotation must be described in the report.** Labelling
1,335 calls from a blank sheet was judged too slow, so the labels were drafted
automatically and will be corrected by the author rather than written from
scratch.

`data/annotation/sheet_draft.csv` holds a draft role and essential flag for
every one of the 1,335 calls, each row marked `annotator=llm-draft` and
`reviewed=no`. Distribution: 831 PREPARATORY, 262 TRIGGER, 242 EXTRACTION.
76 rows carry a `CHECK:` note where the drafting rules are least reliable.

**Review of the 76 flagged rows.** Each was classified a second time with a
written one-line reason, in `data/annotation/review/check_rows_review.csv`:
11 answered by the author directly, 65 classified by an LLM from the full
trace for the author to check. 44 of the 76 differ from the original draft,
which is itself worth reporting: the rows flagged as uncertain really were the
unreliable ones. A row becomes ground truth only when the author writes `yes`
in its `confirm` column and runs `python pipeline/apply_review.py`, which is
the only place `reviewed=yes` is ever set. Rows applied this way are tagged
`annotator=llm-then-author` or `annotator=author`.

**If three-role accuracy is reported from these rows, say what they are.** They
are the 76 *hardest* calls in the corpus, chosen because the drafting rules
were least sure of them. Accuracy measured on them is not representative of the
1,335 calls as a whole and will understate performance. Report it as accuracy
on the flagged subset, never as overall accuracy.

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

### The original blank sheet, kept for reference

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

### What this study can and cannot establish

Read `data/predictions/RESULTS.md`; it is generated from the measurements and
is authoritative. This section says what may be concluded from it.

**The full ladder ran.** C0 to C4 cover all 28 cases; C5 covers 26, because two
victim contracts have no verified source on Etherscan and the pipeline refused
to substitute anything for them.

| Condition | hit@1 | hit@1 95% CI | hit@3 | Precision | Recall | F1 | F1 95% CI | Called TRIGGER | Lift |
|-----------|-------|--------------|-------|-----------|--------|-----|-----------|----------------|------|
| C0 rules  | 0/28  | [0.00, 0.00] | 13/28 | 0.209 | 0.699 | 0.322 | [0.109, 0.496] | 23.3% | 3.00 |
| C1 masked | 8/28  | [0.14, 0.46] | 11/28 | 0.144 | 0.839 | 0.245 | [0.123, 0.359] | 40.7% | 2.06 |
| C2 names  | 8/28  | [0.14, 0.46] | 15/28 | 0.219 | 0.806 | 0.345 | [0.149, 0.545] | 25.6% | 3.15 |
| C3 actors | 9/28  | [0.18, 0.50] | 16/28 | 0.207 | 0.785 | 0.327 | [0.142, 0.497] | 26.4% | 2.97 |
| C4 fewshot| 12/28 | [0.25, 0.61] | 16/28 | 0.194 | 0.828 | 0.315 | [0.147, 0.481] | 29.7% | 2.79 |
| C5 source | 13/26 | [0.31, 0.69] | 20/26 | 0.223 | 0.878 | 0.355 | [0.165, 0.531] | 30.6% | 2.87 |

### The result: information improves ranking, not discrimination

This is the finding the report should be built on, and it is a genuinely
two-sided one.

**What improves.** hit@1 rises monotonically as information is added, from
0/28 with rules alone to 13/26 with the victim's source: 0%, 29%, 29%, 32%,
43%, 50%. The C0 and C5 intervals do not overlap ([0.00, 0.00] against
[0.31, 0.69]), so that improvement is established, not noise. hit@3 rises the
same way, 13 to 20. **Given more context, the model puts the genuinely
vulnerable call nearer the front of its list.**

**What does not improve.** F1 is flat across the whole ladder, 0.245 to 0.355,
with every interval overlapping every other. Lift over chance is flat at
roughly 2.1 to 3.2. Precision never exceeds 0.223 in any condition. And the
share of calls labelled TRIGGER *rises* with information, from 25.6% at C2 to
30.6% at C5, against a benchmark rate of 7.0%.

**So the model is getting better at prioritising, and no better at being
selective.** Extra context moves the right answer up the list without reducing
the number of wrong answers on it. That distinction is the contribution: it
says something specific about what an LLM does with trace context, rather than
reporting an accuracy and stopping.

### Secondary observations worth a paragraph

- **Masking hurts most.** C1, with every identifier removed, labels 43.6% of
  calls TRIGGER, far more than any other condition, and is the only condition
  that scores below the rule baseline on F1. Structure alone is not enough.
- **Agreement with the drafted labels plateaus early**: 0.67 at C2, 0.70 at C3,
  0.70 at C4, 0.69 at C5. Whatever the later rungs add, it is not general
  agreement with a structural reading of the trace.
- **EXTRACTION shrinks monotonically** as information is added, 23.2% at C0
  down to 12.8% at C5, while PREPARATORY holds near 55%. The model reallocates
  from EXTRACTION into TRIGGER as it learns more.

### Three metric errors this study made and corrected

Each changed a conclusion, and each belongs in the methodology:

1. **`hit@any` reported alone** flattered every condition; a model labelling
   40% of calls TRIGGER hits by volume. Fixed by always reporting precision and
   the trigger rate beside it.
2. **Precision compared across transaction sizes** looked like a collapse on
   large traces. The benchmark marks 23.1% of calls in a ten-call transaction
   and 2.8% in a hundred-call one, so precision falls automatically. Lift over
   chance removes the effect; the claim was withdrawn.
3. **Conditions ranked on point estimates** gave two opposite answers as data
   arrived. Bootstrap intervals show F1 cannot separate them at all, which is
   why the finding above rests on hit@1, where the intervals do separate.

### A contrast for Chapter 5

On C06 (Seneca, 3 calls) condition C1 labels exactly one call TRIGGER and
matches the benchmark exactly, while C0 labels two of three. Use it to show what
success looks like, but do not generalise from it: the lift table shows tiny
transactions are not systematically easier once the base rate is accounted for.
`data/case_studies/` holds the generated material.

## Finishing the condition ladder

The ladder is run one condition at a time and each run is resumable, because
the daily token limit will usually interrupt it.

```bash
python pipeline/classify.py --condition C3 --all --only-missing
python pipeline/classify.py --condition C4 --all --only-missing
python pipeline/classify.py --condition C5 --all --only-missing
python pipeline/evaluate.py          # rewrites metrics.json and RESULTS.md
python pipeline/case_studies.py      # rewrites the Chapter 5 material
```

`--only-missing` skips cases already in the output file, and results are merged
into it rather than overwriting, so running the same command again the next day
picks up exactly where the budget ran out. Nothing is lost by being cut off.

Budget arithmetic, measured: a condition-run over 28 cases costs 75,000 to
150,000 tokens against a 200,000 daily limit, so **roughly one and a half
conditions fit in a day**. C4 and C5 carry few-shot examples and victim source
in every request, so they cost more than C1 to C3.

After any run, re-run `evaluate.py`. It marks which conditions cover all 28
cases, and nothing incomplete should be compared against anything complete.

## What is blocked, and on what

| Blocked | Needs |
|---------|-------|
| Three-role accuracy over the whole corpus | reviewing the remaining 1,259 drafted rows; only the 76 flagged ones were reviewed |
| Cohen's kappa | **dropped**: no second independent human annotator |

Everything else is done. Chapters 5 and 6 can be written now.

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

The Alchemy key in `.env` is also present in this repository's public history,
at commit `fd912b4` in `faultseeker/faultseeker.py`, as a commented-out URL.
Deleting the file did not remove the blob. The two were confirmed identical by
hashing.

**The author has decided not to rotate it**, having judged the exposure
acceptable for a free-tier archive-RPC key. Recorded here so the decision is
visible rather than looking like an oversight. The Groq key in that same commit
is also public, but the current one differs, so it was already replaced.

The pipeline itself commits no keys: `.env` is gitignored, and `rpc_call`
redacts URLs from every error message after a 429 printed one to the terminal
during the batch fetch. The exposure is historical, not ongoing.

## Where to read the detail

- `data/CHECKPOINT.md` — full per-case table, fidelity evidence, parser audit.
- `data/frames/summary.csv` — one row per case, machine-readable.
- `data/frames/<txhash>.json` — parsed frames plus on-chain facts per case.
- `data/traces/<txhash>.txt` — raw `cast run` output per case.
- `latex/CHAPTER_FIXES.md` — the citation fixes still to apply in Overleaf.
