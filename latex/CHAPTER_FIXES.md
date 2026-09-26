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

### E2. The central result, and what may not be claimed

**Read `data/predictions/RESULTS.md` for the numbers.** It is generated by
`pipeline/evaluate.py` and cannot drift from the measurements. Do not copy a
table out of any prose file, including this one.

**The conditions cannot be separated on F1.** Bootstrapping whole cases 2000
times gives 95% intervals that overlap heavily (C0 [0.109, 0.496], C1 [0.123,
0.359], C2 [0.149, 0.545]). With 28 cases a difference of 0.02 F1 is inside
sampling noise. An earlier version of this note told you to report that the C0
baseline had the best F1. **That instruction is withdrawn.** Do not rank the
conditions on F1 in either direction.

What the data does support, and what Chapter 6 should be built around:

1. **Every condition over-labels TRIGGER by three to six times.** The benchmark
   marks 7.0% of calls as the vulnerable function; the conditions mark 23.3% to
   40.7%. Recall is high (0.70-0.84) and precision never exceeds 0.22. The model
   locates the flawed call but cannot separate it from the setup that enabled it
   or the drain it caused. This is a large, consistent effect, unlike the
   differences between conditions.
2. **Masking identifiers changes behaviour substantially.** Everything masked:
   40.7% of calls called TRIGGER. Decoded names: 25.6%. That is measured over
   1,335 calls rather than 28 cases. Report it as a behavioural effect, not as a
   significant accuracy improvement.
3. **No condition is close to usable precision, and none clearly beats a
   lexical rule baseline that costs nothing to run.** For a reader deciding
   whether to deploy this, that is the most useful sentence in the chapter.

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
TRIGGER and matches the benchmark exactly, while C0 labels two of three. The
aggregate over-labelling is not uniform — it is a large-trace failure.

### E4. The tool exists and should be described as a deliverable

`pipeline/analyse.py` takes any transaction hash on a supported chain, replays
it, verifies the replay against the receipt, parses the call tree, labels every
call, and prints the attack as a narrative. It is not limited to the 28
benchmark cases. Chapter 4 or 7 should describe it as the artefact the study
produced, and should repeat its own caveat: because the model over-labels
TRIGGER, the tool presents that role as a shortlist to read rather than a
verdict.
