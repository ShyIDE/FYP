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
