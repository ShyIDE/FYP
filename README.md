# Labelling the role of every call in a DeFi attack transaction

FYP SCSE8338, Brandon Chiu, NTU CCDS, AY2025/2026.

## The question

When a DeFi protocol is exploited, the attack is usually one transaction. That
transaction can contain hundreds of calls. An incident responder reading it
wants to know what happened: which calls set the attack up, which one actually
broke the protocol, and which took the money out.

FaultSeeker (Sun et al., ASE 2025) answers a narrower question — it ranks which
*function* was vulnerable. This project asks what each *call* was for, which
turns a ranked list into an account of the attack. Every call gets one of three
roles and a separate judgement of whether the attack needed it:

| Role | Meaning |
|------|---------|
| `PREPARATORY` | sets up the conditions the exploit needs: flash loans, approvals, deploying helpers, reading state |
| `TRIGGER` | exploits the vulnerability itself; remove it and the attack stops working |
| `EXTRACTION` | realises or secures the profit: draining, swapping out, repaying the loan |

The research question is not "can an LLM do this" but **what information does an
LLM need in order to do it, and where does it fail?** That is answered with a
ladder of prompting conditions, each adding exactly one thing to the one before,
so any change in the numbers is attributable to that one addition.

| Condition | What it adds |
|-----------|--------------|
| `C0` | no model at all: transparent lexical and structural rules, the floor to beat |
| `C1` | the model, with every contract and function name masked — call structure only |
| `C2` | decoded contract addresses and function names |
| `C3` | which address is the attacker and which is the attack contract |
| `C4` | few-shot examples, drawn only from the development split |
| `C5` | the victim contract's verified source |

No model is trained. The prompting condition is the experimental variable.

## The finding so far

Measured against the benchmark's own ground-truth vulnerable function, the one
role that can be scored without human annotation:

| Condition | hit@1 | Precision | Recall | F1 | Called TRIGGER | Benchmark | Lift over chance |
|-----------|-------|-----------|--------|-----|----------------|-----------|------------------|
| C0 rules  | 0/28  | 0.209 | 0.699 | **0.322** | 23.3% | 7.0% | **3.00** |
| C1 masked | 8/28  | 0.144 | 0.839 | 0.245 | 40.7% | 7.0% | 2.06 |
| C2 named  | 6/23  | 0.117 | 0.622 | 0.196 | 24.5% | 4.6% | 2.54 |

**Every condition over-labels `TRIGGER` by three to six times.** The models
locate the flawed call — recall is high — but cannot separate it from the setup
that enabled it or the drain it caused. High recall with precision near 0.15 is
a wide net, not discrimination. The rule baseline currently has the best F1 and
the best lift: **no model condition beats it yet.**

Two reporting rules this project follows as a result:

- `hit@k` is never given on its own. A model that calls half a transaction a
  `TRIGGER` scores well on `hit@any` by volume alone.
- Precision is never compared across groups of different size without **lift
  over chance** (precision divided by the rate random marking would achieve).
  An earlier version of this analysis appeared to show performance collapsing on
  large traces; once the base rate was divided out the effect vanished, because
  the benchmark marks 23.1% of calls in a ten-call transaction and 2.8% in a
  hundred-call one. Lift is flat across sizes, at roughly 1.4x to 4.3x.

## Using the tool

```bash
python pipeline/analyse.py 0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d
python pipeline/analyse.py 0x24a68d2a4bbb02f398d3601acfd87b09f543d935fc24862c314aaf64c295acdb --chain bsc
```

It replays the transaction, checks the replay against the on-chain receipt,
parses the call tree, labels every call, and prints the attack as a narrative.
It works on any transaction, not only the benchmark cases.

It does **not** decide whether a transaction is an attack; it assumes you
already believe that. And given the over-labelling above, its `TRIGGER` set is a
shortlist to read, not a verdict.

## Reproducing the study

```bash
pip install -r requirements.txt
cp .env.example .env            # then fill in the keys

python pipeline/fetch_traces.py --all          # replay and parse all 28 cases
python pipeline/trace_parser.py --selftest     # parser self-tests
python pipeline/draft_annotations.py           # draft labels for human review
python pipeline/classify.py --condition C3 --all
python pipeline/evaluate.py
python pipeline/case_studies.py
```

Foundry is required (`cast`); install with `foundryup` and either put it on
`PATH` or set `CAST_BIN` in `.env`.

## What is verified, and what is not

The project's rule is that a number in the report must correspond to something
that was actually run, and a failure must be visible rather than smoothed over.

- **25 of 28 replays are verified**: the replayed gas equals the on-chain
  receipt exactly. C03, C26 and C27 do not match and are reported as excluded
  with the reason, not quietly dropped. `fetch_traces.py` exits non-zero when a
  replay does not match.
- **The parser is audited against the raw traces**: 1,335 call lines in,
  1,335 frames out, no frame missed or invented, and the parent, depth, index
  and child-count invariants hold for every frame.
- **The annotation is LLM-drafted and author-reviewed**, not independent human
  annotation. Only rows marked `reviewed=yes` count as ground truth;
  `evaluate.py` scores unreviewed drafts separately and labels them provisional.
  Cohen's kappa is therefore unavailable and its absence is reported.
- **Two claims were withdrawn** when the evidence contradicted them. See
  `data/CHECKPOINT.md`.

## Layout

| Path | What it holds |
|------|---------------|
| `data/cases.csv` | the 28 benchmark cases, 7 categories x 4 |
| `data/traces/` | raw `cast run` output, one file per transaction |
| `data/frames/` | parsed call frames and on-chain facts, plus `summary.csv` |
| `data/annotation/` | the annotation sheet, the drafted labels, the guidelines |
| `data/predictions/` | one file per condition per run, with the raw model replies |
| `data/case_studies/` | generated Chapter 5 material |
| `data/CHECKPOINT.md` | replay fidelity and the parser audit |
| `STATUS.md` | current state, written for the report-writing chat |
| `pipeline/` | the code; see each module's docstring |

## Limitations

- Long transactions are split into windows of at most 40 calls, forced by the
  provider's output-token limit. In a windowed case the model sees a slice of
  the call list rather than the whole transaction at once.
- The provider allows 200,000 tokens per day, so a condition-run costs most of
  a day's budget and repeated runs are expensive.
- Three of the 28 replays are unverified, all on BSC, cause undetermined.
- The three-role classification has no fully human-annotated ground truth, so
  the headline metric is restricted to the one role the benchmark grounds.
- The committed traces were fetched without an Etherscan key, so they carry bare
  addresses rather than verified contract names. All recorded results come from
  those traces. Re-fetching with a key set would change the model's input and
  would require re-running every condition. See `data/CHECKPOINT.md`.
