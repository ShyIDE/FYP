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
