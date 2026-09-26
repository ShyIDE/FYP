# Annotation guidelines: call role and essentiality

Every call in an attack transaction gets exactly one **role** and one
**essential** flag. Annotate a transaction as a whole, top to bottom, not as
isolated rows: a call's purpose is only visible against the rest of the attack.

## The three roles

Assign the role by asking **what the call contributes to the attack**, not what
the function is named and not who it belongs to.

### PREPARATORY
Sets up the conditions the exploit needs. The attack is not yet happening.
Typical cases:
- taking a flash loan, or borrowing the capital the attack will use
- `approve` calls that let a later transfer move tokens
- deploying a helper contract (`CREATE`)
- reading state to size the attack: `balanceOf`, `getReserves`, price queries
- swaps performed only to acquire the asset the exploit needs

### TRIGGER
Exploits the vulnerability. **The test: if you removed this call and changed
nothing else, would the attack stop working?** If yes, it is a TRIGGER.
Typical cases:
- calling the vulnerable function itself
- the re-entrant call that returns into a victim mid-update
- the call that passes a manipulated price or a forged parameter to the victim
- the unauthorised call that an access-control flaw fails to reject

A transaction usually has few TRIGGER calls. If you have labelled many, check
whether you are labelling the *consequences* of the trigger rather than the
trigger itself.

### EXTRACTION
Realises or secures the profit, after the vulnerability has been exploited.
Typical cases:
- draining a balance, or transferring stolen funds out
- swapping stolen tokens into a stable asset or ETH
- repaying the flash loan
- moving funds to the attacker's own account

## Boundary rules

These exist because they are the cases annotators disagree on.

1. **A flash loan is split.** Taking the loan is PREPARATORY; repaying it is
   EXTRACTION. The repayment is part of realising the profit, because the
   attack only pays out once the loan is settled.
2. **A swap is classified by what it is for.** Acquiring the asset the exploit
   needs is PREPARATORY; converting stolen value is EXTRACTION.
3. **Read-only calls are almost always PREPARATORY.** A `STATICCALL` cannot
   change state, so it can rarely be the trigger. The exception is a read whose
   *return value* is what the victim relies on, for example a manipulated
   price the victim reads; label that TRIGGER.
4. **A `DELEGATECALL` into an implementation keeps the role of the call that
   entered the proxy.** Do not label the proxy hop separately from its purpose.
5. **Repetition does not change the role.** If the same exploit call is made
   forty times in a loop, every one of those calls is a TRIGGER.
6. **Judge by effect, not by name.** A function called `transfer` can be the
   trigger if transferring is what breaks the invariant.

## The essential flag

Separate from the role. Mark `yes` if removing this call would make the attack
fail or lose value; `no` if the attack would still succeed without it.

Calls that are usually **not** essential:
- balance checks the attacker made only to observe or log
- `console.log` calls left in the attacker's contract
- duplicated queries that read the same value twice

A TRIGGER call is essential by definition. A PREPARATORY or EXTRACTION call may
be either. Recording it separately from the role is deliberate: it lets the
experiment ask whether a model can tell a load-bearing setup step from an
incidental one.

## Filling in the sheet

- `role`: one of `PREPARATORY`, `TRIGGER`, `EXTRACTION`. Never blank.
- `essential`: `yes` or `no`. Never blank.
- `annotator`: your initials, so the two annotators can be told apart.
- `notes`: free text. Use it for any row you were unsure about; those rows are
  worth reviewing when the agreement figure is computed.

Columns to your left are context and should not be edited. `target_role` marks
the attacker's account, the attack contract and any contract the benchmark
records as vulnerable. `is_gt_vuln_function` marks the function the benchmark
names as the vulnerability. **It is a hint, not the answer**: the vulnerable
function is usually a TRIGGER, but the benchmark records one function per case
while a transaction often has several trigger calls.

## How the labels were actually produced

This section records what happened, not what was planned, because the report
has to describe the annotation honestly.

The labels were **drafted automatically and reviewed by the author**, not
written from scratch by a human. `pipeline/draft_annotations.py` produced a
draft role and essential flag for all 1,335 calls: the trigger calls were
identified by reading each of the 28 traces, and every other call was labelled
by the structural rules above. Each drafted row is marked
`annotator=llm-draft` and `reviewed=no`, and becomes ground truth only when a
human marks it `reviewed=yes`. `pipeline/evaluate.py` scores unreviewed rows
separately and labels them provisional.

**Cohen's kappa is not available.** It measures agreement between two
independent human annotators, and there is only one annotator on this project.
Agreement between two model passes would measure the model's self-consistency,
which is a different quantity already reported as run agreement, so it is not
substituted here. The absence of an inter-annotator reliability figure is a
stated limitation of the study.

One consequence to keep in mind when reading any agreement number: the drafting
rules in this document are structural, and so is the C0 baseline in
`classify.py`. They share assumptions, so C0 agrees with the draft more than it
deserves, and that comparison is not a measure of C0's accuracy.

## If a second annotator does become available

`second_annotator.csv` holds the subset to use: one whole transaction per
category, 7 cases and 390 rows. They should label it from these guidelines
alone, without seeing the drafted labels, after which kappa can be computed
over the overlapping rows for role and for essential separately.
