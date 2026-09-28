# Overleaf fixes to make now (Step 4)

Use Overleaf's search (Ctrl+F) to find each piece of text. The line breaks in
your file may differ slightly, so search for the short phrase in quotes.

## A. references.bib

1. Replace the three entries `sun2024`, `liu2026` and `sun2023` with the
   versions in `references_fixes.bib` (PART A). Keep the same keys.
2. Paste the five new entries (PART B) at the end.
3. Compile twice.

## B. Wrong or unsupported citations

**Chapter 2**: search `Oyente \cite{chen2026}` (chen2026 is the phishing paper)

- replace with: `Oyente \cite{luu2016oyente}`

**Chapter 3**: search `Groq inference API \cite{foundry2026}` (Foundry is not Groq)

- replace with: `Groq inference API` (delete the citation)

**Chapter 4**: search `professor's guidance`

- replace `This design follows the professor's guidance \cite{sun2024} to position`
- with `This design follows the project specification to position`

**Chapter 4**: search `preliminary testing` (no such testing was done, and
FaultSeeker does not define a three-role scheme). Replace the two sentences
from "A five-role scheme was rejected..." to "...technical report \cite{sun2024}." with:

```latex
A finer-grained scheme, for example one that splits extraction into
loan repayment and profit-taking, was not adopted, because a single call
such as a flash-loan repayment can serve both purposes and would make the
labels ambiguous. Whether a call is essential to the attack is recorded
separately, as a yes/no flag alongside its role.
```

**Chapter 4**: search `primary experimental variable`

- replace `primary experimental variable \cite{sun2024}.` with `primary experimental variable.`

## C. Leave for later (these get rewritten from real results)

- The Euler hash ending `...965cc70` in Chapters 3 and 4 is wrong; the real
  one ends `...b6111d`. The figures and captions that use it (Chapter 3
  sections 3.2 to 3.5, Chapter 4 output figures) came from sample data, so
  they will be replaced in Step 6. Do not submit them as they are.
- Chapter 1: the name FAULTSEEKER and the "first system" claim. FaultSeeker
  is an existing ASE 2025 paper; this project extends it. Rewritten in Step 7.
- Chapter 3 Figure 3.2 (category percentages) was estimated, not measured.
  It is replaced by the real category counts of the 28 cases.

## D. Added 2026-09-25, after the traces were fetched and the parser audited

These come from real runs. Details and evidence in `data/CHECKPOINT.md` and
`STATUS.md`.

### D1. Withdraw both parser claims (Chapter 3)

Two claims about FaultSeeker's parser were wrong and must not appear:

- that it attributes depth by counting `|` characters and so misplaces calls
  nested under a parent's last child
- that it cannot parse contract-creation transactions

The first does not happen in real `cast` output: every frame ends with its own
return line, so a call is never drawn as a last child. Measured over all 28
traces, 0 of 1307 non-root calls carry the last-child marker. The second was a
bug in *this* project's parser, now fixed, not a property of FaultSeeker's.

Neither can be asserted at all, because **no copy of FaultSeeker's parser is in
this repo**. Search Chapter 3 for any sentence comparing the two parsers and
delete it.

What may be said instead, because it was measured: C03 and C26 are
contract-creation transactions (`tx.to` is null, the attack runs in the
constructor, the trace root is a CREATE node), exactly 2 of 28. A parser that
accepts only a call as its root yields zero frames on them and fails silently.
Write that as a parser-design observation, attributed to nobody.

### D2. Figure 3.2, real numbers

The dataset is exactly balanced: 7 categories, 4 cases each, 14.3% each. A
varying-percentage chart is wrong in shape, not only in value.

Frames per category, measured: reentrancy 353, arithmetic 290, business_logic
221, price_oracle_manipulation 186, token_specific 161, access_control 65,
arbitrary_external_call 59.

### D3. Corpus figures for Chapter 3

28 transactions, 1,335 call frames. Frames per transaction: min 3, median 35,
max 151 (C16 Euler). Max depth: min 2, median 4.5, max 82 (C24 Game).
Composition: 511 staticcalls, 219 delegatecalls, 1,140 emitted events, 68
frames where `cast` knew only the 4-byte selector.

**25 of 28 replays are verified faithful.** C03, C26 and C27 (all BSC) replay
cleanly but their gas does not match the receipt; cause undetermined. Report 28
fetched and 25 verified, and name the three exclusions. Do not present 28 as
all verified.

### D4. The Euler hash, again

`0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d`, block
16,817,996, gas 1,949,994, 151 frames, max depth 11, `donateToReserves` at
frame 64.

### D5. Methodology points that must be stated in Chapter 4

- The victim contract's identity comes from the ground truth, so it is withheld
  from the model until condition C5. C3 reveals only the attacker's account and
  the attack contract, both readable from the transaction itself.
- C4's few-shot examples come from dev cases only; test cases never enter a
  prompt.
- Long transactions are split into windows of at most 40 calls, forced by the
  provider's 1,000 output-tokens-per-minute limit. Every case goes through the
  same windowing code. State the limitation: in a windowed case the model sees
  a slice of the call list, not the whole transaction at once.
- `hit@k` means: predicted TRIGGER calls ranked by execution order, and hit@k
  asks whether any of the first k is a call to the benchmark's function.
  Execution order is used because the model returns labels, not scores.

## E. Added 2026-09-26. The results chapter, and a metric that was wrong

### E1. Never report hit@k on its own

An earlier note gave `hit@any` figures without saying how many calls the model
labelled TRIGGER. That flatters every condition: a model that calls 40% of a
transaction the exploit will hit the right call often by volume alone. Any
hit@k number in the report must appear beside precision and the trigger rate.

### E2. The central result

**Read `data/predictions/RESULTS.md` for the numbers.** It is generated by
`pipeline/evaluate.py` and cannot drift. Do not copy a table out of any prose
file, including this one.

The full ladder ran: C0 to C4 over all 28 cases, C5 over 26 (two victim
contracts have no verified source and the pipeline refused to substitute
anything).

**The finding is two-sided, and both halves matter:**

1. **Information improves ranking.** hit@1 rises monotonically as context is
   added: 0/28 with rules alone, then 29%, 29%, 32%, 43%, and 50% with the
   victim contract's source. The C0 and C5 bootstrap intervals do not overlap
   ([0.00, 0.00] against [0.31, 0.69]), so this is established, not noise.
   hit@3 rises the same way, 13 to 20.
2. **Information does not improve discrimination.** F1 is flat across the whole
   ladder, 0.245 to 0.355, with every bootstrap interval overlapping every
   other. **Do not rank the conditions on F1.** Precision never exceeds 0.223,
   and the share of calls labelled TRIGGER *rises* with information, from 25.6%
   at C2 to 30.6% at C5, against a benchmark rate of 7.0%.

Write it as: extra context moves the right answer up the model's list without
removing the wrong answers from it. The model becomes better at prioritising
and no better at being selective. That is a specific claim about what an LLM
does with execution-trace context, which is worth more than an accuracy figure.

Supporting observations, a paragraph each:

- **Masking hurts most.** C1, with every identifier removed, labels 43.6% of
  calls TRIGGER, far more than any other condition, and is the only condition
  scoring below the rule baseline on F1. Structure alone is not enough.
- **EXTRACTION shrinks monotonically** as information is added, 23.2% of calls
  at C0 down to 12.8% at C5, while PREPARATORY holds near 55%. The model
  reallocates from EXTRACTION into TRIGGER as it is given more context.
- **Agreement with the drafted labels plateaus at C3** (0.67, 0.70, 0.70, 0.69),
  so whatever C4 and C5 add, it is not broad agreement with a structural
  reading of the trace — it is specifically better placement of the top answer.

### E2b. Three metric errors, worth a methods paragraph each

Each one changed a conclusion, and reporting them is a strength rather than an
admission:

1. **hit@any reported alone** flattered every condition, because a model
   labelling 40% of calls TRIGGER hits by volume. Fixed by always printing
   precision and the trigger rate beside it.
2. **Precision compared across transaction sizes** looked like a collapse on
   large traces. The benchmark marks 23.1% of calls in a ten-call transaction
   and 2.8% in a hundred-call one, so precision falls automatically. Lift over
   chance removes the effect entirely and the claim was withdrawn.
3. **Conditions ranked on point estimates** gave two opposite answers as data
   arrived: C0 "best" while C2 covered 23 of 28 cases, then C2 "best" once it
   completed. Bootstrap intervals show neither ranking is established.

### E3. Chapter 5 material is generated, not written by hand

`data/case_studies/` holds one markdown file per selected case, produced by
`pipeline/case_studies.py` from the traces and the predictions. Each has the
transaction facts, the labelled call tree, and which benchmark function the
model found or missed. The interpretation sections are left blank deliberately;
that is the author's to write.

The four cases were chosen for what they expose, and the report should say so:
C16 the largest trace at 151 calls, C24 the deepest at 82 levels with the
exploit repeated 42 times, C06 a three-call single-delegatecall exploit, and
C27 a case whose replay could not be verified.

Useful contrast for Chapter 5: on C06, condition C1 labels exactly one call
TRIGGER and matches the benchmark exactly, while C0 labels two of three. **Do
not** call this a large-trace failure: section E2's lift-over-chance analysis
found no size trend once the benchmark's own falling base rate is divided out.
Present C06 as one small case where a condition happened to match exactly, not
as evidence that small traces are systematically easier.

### E4. The tool exists and should be described as a deliverable

`pipeline/analyse.py` takes any transaction hash on a supported chain, replays
it, verifies the replay against the receipt, parses the call tree, labels every
call, and prints the attack as a narrative. It is not limited to the 28
benchmark cases. Chapter 4 or 7 should describe it as the artefact the study
produced, and should repeat its own caveat: because the model over-labels
TRIGGER, the tool presents that role as a shortlist to read rather than a
verdict.

## F. Added 2026-09-28. Three-role accuracy, and the Chapter 1 story

### F1. Three-role accuracy now exists, for a reviewed subset only

The author reviewed and confirmed all 76 calls that `draft_annotations.py`
flagged as uncertain (see `data/annotation/review/check_rows_review.csv`).
Each was classified with a written reason — 11 directly by the author, 65
first classified by an LLM from the full trace and then confirmed or corrected
by the author — before being written into `sheet_draft.csv` as `reviewed=yes`.
44 of the 76 differ from the original automatic draft.

**Describe this annotation method plainly: AI-classified, author-reviewed.**
It is not independent human annotation, and Cohen's kappa is still
unavailable — there is one annotator, not two — so its absence stays a stated
limitation. Do not describe the 76-row review as closing that gap.

`data/predictions/RESULTS.md` has the numbers: accuracy with a 95% interval,
macro-F1, essential-F1, per-role precision/recall and a confusion matrix per
condition, all scored against these 76 rows. Two rules for using them:

- **They are accuracy on the flagged subset, not overall accuracy.** These are
  the 76 hardest calls in the corpus, drawn from only 9 transactions. Never
  write "the classifier achieves N% accuracy" from these rows alone.
- **Compare conditions only on the "Compared on the same calls" table** (63
  calls every condition covers). On it: C0 0.25, C1 0.38, C2 0.29, C3 0.41, C4
  0.37, C5 0.52. The ordering is not monotonic and the intervals overlap
  heavily, so no ranking of conditions on three-role accuracy is established.
  The one defensible observation: C5, given the victim's source, scores
  highest on the calls the rules found hardest — consistent with, but not
  proof of, the main ranking finding in section E2.

### F2. The Chapter 1 story: what this project is actually an evolution of

Chapter 1 currently has no framing connecting this project to FaultSeeker
beyond citing it. Use this instead.

**The motivating problem.** An analyst investigating a DeFi exploit manually
traces the attack transaction call by call to work out what happened: what set
the attack up, which call broke the protocol, and where the money went. This
is slow, and it is the actual task FaultSeeker and this project both address.

**What FaultSeeker does.** Given an attack transaction, it ranks which
*function* was probably vulnerable — a single answer, not an account of the
attack.

**What this project does differently, not just more of the same.** It labels
every call in the transaction with the job it did (PREPARATORY, TRIGGER,
EXTRACTION) plus whether the attack needed it. That is a call-by-call
narrative reconstruction, closer to what a human analyst actually produces,
and a strictly harder problem than ranking one function.

**The honest positioning, which must appear somewhere in Chapter 1 or the
conclusion.** This is not a claim that manual analysis has been replaced.
Measured precision on TRIGGER never exceeds 0.223 in any condition (section
E2), so the tool's TRIGGER output is a shortlist an analyst still has to check,
not an unattended verdict — `analyse.py` prints exactly that caveat next to its
own output. Frame the contribution as: **information demonstrably improves
where the AI ranks the true vulnerable call (hit@1 rises from 0% to 50%,
section E2), but does not make it more selective (F1 stays flat, precision
stays low, and the TRIGGER rate rises rather than falls with more context).**
That is a specific, evidenced claim about what execution-trace context does and
does not buy an LLM — a genuine research contribution distinct from "we built
a tool" and defensible against "why not just use FaultSeeker."

### F3. Suggested Future Work paragraph

Something like this belongs in the conclusion, to turn the precision ceiling
into forward motion rather than leave it as a bare limitation:

Closing the gap between ranking and discrimination is the natural next step.
Candidates worth naming: training or fine-tuning specifically to distinguish a
TRIGGER call from its immediate PREPARATORY and EXTRACTION neighbours, rather
than prompting a general model; a second pass that re-examines only the calls
an initial pass marked TRIGGER, rather than judging the whole transaction at
once; or combining the model's ranked shortlist with the kind of static
analysis FaultSeeker already performs, using each to filter the other's false
positives. None of these were tested here; they are proposed on the strength of
where this study's own numbers say the difficulty actually sits.
