# Evals

This directory contains two different kinds of evidence. They answer different
questions and must not be conflated.

| Layer | What it proves | Needs a model? | Release blocker? |
|---|---|---|---|
| Deterministic safety (`w1`, `w2`) | Red-flag rules, emergency handoff metadata, provenance resolution and scope behaviour | No | **Yes** |
| Answer-bearing quality (`rag_w3`, `qa_x01`) | RAGAS/DeepEval answer-quality signals on synthetic fixtures | Yes, through LiteLLM | No (informational only) |
| Judge calibration | Whether a judge agrees with a named human review | Human review; optional judge verdicts | No |

The 60 shipped deterministic cases are safety/provenance cases. They are **not**
answer-bearing RAG or QA quality cases. No RAGAS or DeepEval score is shipped in
a fixture: a score only exists after a framework run against a configured model
alias. Reports from a local run are archived under
[`docs/evidence/`](../docs/evidence/) as run artefacts, not as fixture data or a
clinical-quality claim.

## Layout

```
evals/
  adapters/ragas/adapter.py       optional RAGAS adapter
  adapters/deepeval/adapter.py    optional DeepEval adapter
  calibration/
    judge_calibration.json        10 paired good/bad synthetic answers (20 items)
    reviewer_template.json        reviewer-file template; invalid until completed
  harness/runner.py               deterministic safety gate (existing)
  harness/framework_runner.py     focused answer-quality + calibration runner
  harness/answer_suites.py        answer-suite schema and loaders
  harness/calibration.py          calibration loaders and agreement math
  sets/w1.jsonl, w2.jsonl         30 + 30 deterministic cases
  sets/rag_w3.jsonl               24 RAG cases: question/answer/contexts/ground_truth
  sets/qa_x01.jsonl               24 QA cases: input/actual_output/expected_output/retrieval_context
  tests/                          pytest checks for schemas, ids, calibration and the gate
```

Each answer-bearing suite has 24 cases: 6 `en-IN`, 6 `hi-IN`, 6 `mr-IN` and 6
`mixed-script`. IDs are unique within and across suites. The mixed-script cases
contain both Devanagari and Latin characters.

Every answer-bearing case is labelled `synthetic: true` and
`data_classification: "synthetic_no_phi"`, and its `provenance` block records:

- `synthetic: true`, `contains_phi: false`
- `answer_origin: "authored_fixture"` or `"model_generated"`
- for authored answers: `author`, `authored_at` (ISO date), and no producing model
- for model-generated answers: `producing_model_alias`, `produced_at` (ISO date) and
  `prompt_version`
- `source_refs` with source id, type, title, locator and observation time

Fixtures may not contain `score`, `scores`, `metric` or `metrics` fields. The
loader rejects them, duplicate IDs, missing adapter fields and answers that claim
to be both authored and model-produced. Demo identifiers such as `DEMO-P1042`
are fictional; there is no real patient data.

## Deterministic safety suite (offline)

```bash
# Directly, without Postgres/object-storage persistence:
uv run python evals/harness/runner.py --suite all --no-persist

# Existing compose entrypoint (persists to Postgres; writes evals/reports/latest.md):
scripts/eval.sh --suite all
```

The deterministic gate exits non-zero on failure. Framework scores cannot turn a
failed red-flag or provenance case into a pass. `evals/harness/framework_runner.py`
re-runs this gate and derives `release_gate` from it alone; it has no framework
parameter in `release_gate()` and always reports
`framework_scores_can_override: false`.

## Answer-bearing framework suites

Install the optional dependencies once:

```bash
uv sync --group eval
```

The judge and embeddings must be reachable through LiteLLM. The runner does not
read `.env` automatically; export the variables in the shell (or run inside the
API container, where compose injects them).

Required environment:

| Variable | Purpose |
|---|---|
| `LITELLM_BASE_URL` | Gateway base URL, without `/v1`. On the host this is usually `http://localhost:5708`; inside compose it is `http://litellm:4000`. |
| `LITELLM_MASTER_KEY` | Gateway key; the adapters fail closed without it. |
| `EVAL_EMBEDDING_ALIAS` | RAGAS embeddings alias, default `local_embedding`. |
| `--alias` / judge alias | Default `judge`, resolved through `config/models.yaml` to `external_judge`. A judge is uncalibrated until reviewed. |

Offline validation (no model call, no score, calibration artefact still written):

```bash
uv run python evals/harness/framework_runner.py \
  --suite all --no-judge \
  --calibration-out evals/reports/judge_calibration.json \
  --report evals/reports/framework_offline.json
```

Live runs:

```bash
export LITELLM_BASE_URL=http://localhost:5708
export LITELLM_MASTER_KEY=...   # never commit this value
export EVAL_EMBEDDING_ALIAS=local_embedding

# RAGAS (rag_w3)
uv run python evals/harness/framework_runner.py \
  --suite rag_w3 --framework auto --alias judge \
  --report evals/reports/rag_w3.json

# DeepEval (qa_x01)
uv run python evals/harness/framework_runner.py \
  --suite qa_x01 --framework auto --alias judge \
  --report evals/reports/qa_x01.json

# Both suites, each with its matching framework
uv run python evals/harness/framework_runner.py --suite all --alias judge
```

The framework runner reports per-suite metrics, per-case results and per-language
slices, plus the deterministic safety gate and the calibration artefact. It exits
`0` after scoring (not a pass/fail claim), `1` if safety is blocked or a judge
error occurs, `2` for a schema/configuration error, and `3` when a framework or
required environment is unavailable. If `LITELLM_BASE_URL` or
`LITELLM_MASTER_KEY` is missing it records `unavailable` and makes no model call.

Operational notes for local judges:

- The RAGAS adapter bounds concurrency because the framework default of 16
  workers saturates a local 7B Ollama model and trips the gateway timeout. It
  uses `RunConfig(timeout=600, max_retries=2, max_wait=30, max_workers=2)`.
  A full 24-case RAGAS suite takes roughly 35–45 minutes on the Mac pilot.
- DeepEval passes `base_url` to LiteLLM and needs a provider prefix on the model
  name (`openai/<alias>`) even for an OpenAI-compatible gateway alias. The
  `litellm` package is part of the `eval` dependency group.
- DeepEval writes a cache under `~/.deepeval`; the adapter redirects it to a
  temporary directory because the API container runs with a read-only root
  filesystem.
- The 2026-10-25 evidence run used `--alias local_main` as the judge. It is
  unreviewed; see the calibration section and treat the scores accordingly.

## Judge calibration

`evals/calibration/judge_calibration.json` contains 10 documented pairs (20
items), each with one good and one bad answer, a rubric and review instructions.
The labels in that file are **provisional fixture labels**, not human review.
Until a reviewer file is supplied, the artefact always records:

```json
{
  "calibrated_by": "unreviewed",
  "status": "pending",
  "human_review_performed": false
}
```

Produce the artefact alone:

```bash
uv run python evals/harness/framework_runner.py --calibration-only \
  --calibration-out evals/reports/judge_calibration.json
```

To perform a review, copy `evals/calibration/reviewer_template.json`, label every
item `good` or `bad` against the rubric, set `reviewer_id` and `reviewed_at`, and
set `attested_human_review` to `true`. The loader rejects an un-attested file, a
partial file remains `pending`, and only a complete file becomes `reviewed` with
`calibrated_by` set to that reviewer. Agreement is computed as observed agreement
and Cohen's kappa; kappa is `null` when chance agreement is 1.0. A reviewer file
alone yields `reviewer_vs_fixture` agreement. Judge-versus-human agreement is
computed only when a complete review and externally produced judge verdicts
(`--judge-labels`, schema in the calibration JSON) are both supplied. The
`judge_calibration_status` field distinguishes `pending_human_review`,
`pending_judge_verdicts` and `computed`. No judge verdicts are invented.

```bash
uv run python evals/harness/framework_runner.py --suite all --no-judge \
  --reviewer-file /path/to/reviewer.json \
  --judge-labels /path/to/judge_labels.json \
  --calibration-out evals/reports/judge_calibration.json
```

The target recorded in the calibration file is kappa >= 0.6. A shipped artefact
with `status: "pending"` has not met it.

## Tests and checks

```bash
uv run pytest evals/tests
uv run ruff check evals
uv run ruff format --check evals
uv run mypy evals/tests evals/harness/answer_suites.py \
  evals/harness/calibration.py evals/harness/framework_runner.py
```

The tests cover suite schema validation, duplicate-ID rejection, calibration
agreement math, reviewer attestation, the pending/unreviewed state, and proof
that a failed deterministic case stays failed even when framework metrics are
perfect. `test_no_judge_run_...` exercises the runner without any model call.

## Honest limitations

- The answer fixtures are **authored for this repository** (with AI-assisted
  drafting during development), not generated by a live Sahyog pipeline. They are
  not outputs of a configured model alias and have no producing alias or score.
  Regenerate them with a live runner if a pipeline-produced evaluation is needed.
- Several `actual_output`/`answer` values are deliberately imperfect so that a
  framework run has something to detect. The fixture says so in `provenance.fixture_note`.
- A framework score is an answer-quality signal, not clinical validation, and is
  not a release gate. Only the deterministic safety gate is.
- The calibration dataset is small (10 pairs / 20 items) and unreviewed. No human
  review, clinical sign-off or kappa target has been achieved in this build.
- Framework results require the optional dependencies and a reachable LiteLLM
  gateway with the configured judge and embedding aliases. If either is missing,
  the runner reports `unavailable` instead of inventing a score.
- Per-language slices are only as representative as 6 synthetic cases per language;
  treat them as smoke signals, not language-quality certification.

## X-01 nursing drafts: live generation and clinician grading (G-13)

`sets/nursing_x01.jsonl` only checks intent shape. Acceptance of real drafts needs a
running stack and a named clinician:

```bash
python -m evals.harness.nursing_x01_live --username doctor.rao      # drafts JSON + grade CSV template
# clinician fills accept/edit/reject (+ grader name, attested) in the CSV
python -m evals.harness.nursing_x01_grades --drafts <drafts.json> --grades <grades.csv>
```

Both tools record errors instead of mocking, and the report always has `closes_gap: false`.
G-13 stays open until 20 live drafts are graded by a named, attested clinician and the
result is stored under `docs/evidence/`.
