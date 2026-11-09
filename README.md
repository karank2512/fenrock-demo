# complaint-triage

A small working demo of AI-assisted complaint intake for a fictional bank. Messy
complaint emails go in; each one comes out either

- **routed** to the owning team queue with a recommended next action a human approves, or
- **held** with the exact reason it needs human review.

Every decision is appended to an audit log with the inputs, the checks that fired, and
the reason, so any decision can be reconstructed afterward.

Everything here is synthetic. Meridian Mutual Bank is fictional, the policy is invented
(`docs/policy-pack.md`), and the complaint corpus is invented. The demo does not and
cannot reply to a customer, resolve a complaint, or touch an account. It makes no
regulatory or compliance claim: the audit log shows a method, nothing more.

## How it works

1. **Deterministic checks decide.** Escalation triggers (legal threats, discrimination
   claims, regulator mentions, amounts over $25k, safety, unauthorized-transaction
   claims, duplicates) always hold for a human and run on the raw email text, so an
   extraction error cannot bypass them. Required fields (name, account reference,
   product, clear category, amount and date when material) are checked in policy order;
   the first gap is the hold reason. If the customer says they don't know where the
   complaint belongs, it is held rather than guessed.
2. **The model only reads.** With `--fields-mode llm`, a model extracts fields (name,
   account, amount, date, summary) through `scripts/claude_extract.sh`, a restricted,
   toolless, session-free CLI call. The model's fields must agree with the deterministic
   parse; any material disagreement holds the case (`extraction_disagreement:<field>`).
   The model never routes.
3. **Humans finish.** `complaint_triage.review_app` is a local queue where a person
   approves recommendations or assigns held cases. Approving records the approval; it
   never sends anything.

Two kinds of process-tampering are flagged, deliberately distinct:

- `injection_attempt`: adversarial instructions embedded in the complaint text
  ("ignore your rules", "skip all checks", "do not hold this", fake system notes).
  The pipeline never follows complaint-text instructions; it flags and decides by
  policy.
- `writer_withdrawal`: the customer retracting or demanding deletion of their own
  complaint. Not an attack - an ordinary request a human must handle, because the demo
  never deletes records.

## Setup

Python 3.9+, standard library only. No dependencies to install.

```
python3 -m unittest discover -s tests -v
```

The optional model step uses the machine owner's own Claude Code CLI login; it is not
required for the deterministic path or the tests. Set `FENROCK_CLAUDE_BIN` if the CLI
is not on PATH.

## Run it

```
# deterministic only, no model calls
python3 -m complaint_triage.run --corpus corpus/corpus-dev-15.json --out out/dev-det --fields-mode none
python3 -m complaint_triage.score --results out/dev-det/results.json --expected corpus/corpus-dev-15.json

# with the model extraction + cross-check
FENROCK_LLM_CMD="$PWD/scripts/claude_extract.sh" python3 -m complaint_triage.run --corpus corpus/corpus-dev-15.json --out out/dev-llm --fields-mode llm
python3 -m complaint_triage.score --results out/dev-llm/results.json --expected corpus/corpus-dev-15.json

# human review queue (local web app on 127.0.0.1, stdlib http.server)
python3 -m complaint_triage.review_app --out out/dev-det --corpus corpus/corpus-dev-15.json
```

## Evaluation

The scorer compares decisions, queues, hold reasons, and tampering flags against a
held-out corpus of 40 complaints whose expected answers were frozen (hash-recorded)
before the pipeline was implemented. It reports decision matches, **wrong auto-routes**
(cases that should have been held but were routed), reason mismatches, and flag
outcomes per kind.

Results from the most recent recorded run (frozen 40-case corpus, model extraction via
Claude Haiku):

First recorded run (2026-11-09): 34/40 decisions matched, with one wrong auto-route
and five other misses. Every miss was root-caused and fixed, and each fix has a
regression test (33 deterministic tests in total).

Second recorded run (2026-11-09, same frozen corpus, code with those fixes): **39/40
decisions matched, 18 routed / 22 held, 0 wrong auto-routes observed.** All 4
process-tampering cases were flagged: 3 as `injection_attempt`, 1 as
`writer_withdrawal`. The one remaining mismatch is a hold-reason label on a case that
is held either way; the frozen key was left unrepaired.

How to read these numbers:

- The second run was informed by the first run's failures. That is a fix-and-recheck
  loop, not a fresh independent validation.
- The post-fix run is a recovery run: a first attempt was interrupted at 35/40 cases
  by a runner-side cleanup bug (partial log preserved, never scored, not used for
  tuning), then the 40-case run was repeated identically. Total post-fix model calls:
  75.
- Zero observed wrong auto-routes across 40 synthetic cases is not a guarantee of zero
  errors on real email.

Honest limits:

- The policy, both corpora, and the expected answers were written by one author in one
  exercise. Freezing before implementation prevents tuning to the answers, but it is
  not an independent evaluation, and 40 invented complaints say nothing about real
  complaint distributions.
- The frozen 40-case corpus and its answer key are kept out of this repository on
  purpose, so the holdout stays usable.
- The frozen key predates the injection/withdrawal flag split: it marks both kinds
  `injection_attempt`. The scorer reports the kinds separately against it, unrepaired.
- The review queue is a single-user local app bound to 127.0.0.1. No auth, no
  multi-user state, not a production service.
- Corpus input is validated (shape, unique ids, string fields, size cap), and all
  rendered HTML is escaped, but this is a demo: no rate limiting, no TLS, no persistence
  guarantees beyond the append-only log.

## Layout

```
complaint_triage/   the package: checks, policy, extract, pipeline, run, score, review app
corpus/             synthetic dev corpus (15 complaints with expected decisions)
docs/policy-pack.md the invented bank policy the rules implement
scripts/            optional model extraction wrapper
tests/              unittest suite (deterministic, no model calls)
```
