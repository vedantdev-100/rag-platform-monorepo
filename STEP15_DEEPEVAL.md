# Step 15 update — DeepEval with LM Studio

This package replaces semantic judging with **DeepEval 4.2.8**. Extract it at your application repository root. It adds `evals/step15_deepeval/` without overwriting the previous harness, application files, root dependency environment or generated data. Use the new runner for judging from now on.

Your 25-question FinanceBench selection, uploaded documents and generation captures are reusable. There is no reason to call Groq again just to change evaluators. Judge every saved response with the same local model, then establish a new DeepEval baseline.

## What changed

| Area | Earlier custom harness | Updated harness |
| --- | --- | --- |
| RAG semantic metrics | Our prompts and score formulas | DeepEval's actual metric classes and algorithms |
| Local model integration | Direct OpenAI-compatible calls | Schema-aware `DeepEvalBaseLLM` adapter calling LM Studio |
| Correctness/completeness/citations | Bespoke scoring logic | DeepEval `GEval` with checked-in, fixed task-specific evaluation steps |
| Test-case representation | Custom capture dictionaries | Captures mapped into `LLMTestCase` objects with explicit input/output/reference/context |
| Dataset, capture, pacing and local reports | Our runner | Retained orchestration around DeepEval |
| Dependencies | Host standard library | Separate locked DeepEval environment; no application dependency upgrades |
| Caching | Old custom request cache | Separate DeepEval judge-request cache keyed by exact prompt/schema/model/version |

Python is still used: DeepEval is a Python library. The distinction is who implements semantic evaluation. The built-in scoring is now DeepEval's; data preparation, exact-context capture, quota pacing and report formatting remain harness responsibilities.

Scores are **not directly comparable** with the previous custom baseline. In particular:

- **Contextual Precision** is ranking-sensitive precision based on relevance verdicts; it is not simply useful chunks divided by five.
- **Contextual Recall** checks attribution of reference-answer statements to retrieved evidence. It is not exhaustive corpus/chunk Recall@5.
- Faithfulness follows DeepEval's claim/truth/verdict algorithm and its defaults; the earlier custom claim/quote protocol was different.
- Citation G-Eval outputs are task-specific rubric scores, not exact citation precision/coverage fractions. They are labeled `deepeval_geval_*` in reports.
- Built-in framework prompts improve reuse and testability, not the correctness of every judgment. A weak local judge can still score badly. Human calibration remains necessary.

## Metric mapping

| Scope | DeepEval class | Report metric |
| --- | --- | --- |
| Ranked returned chunks | `ContextualPrecisionMetric` | `deepeval_contextual_precision` |
| Ranked returned chunks vs gold answer | `ContextualRecallMetric` | `deepeval_contextual_recall` |
| Ranked returned chunks | `ContextualRelevancyMetric` | `deepeval_retrieved_context_relevancy` |
| Exact bounded evidence actually sent | `ContextualRelevancyMetric` | `deepeval_context_relevancy` |
| Exact bounded evidence vs gold answer | `ContextualRecallMetric` | `deepeval_context_budget_recall` |
| Completed answer vs exact bounded evidence | `FaithfulnessMetric` | `deepeval_faithfulness` |
| Question and completed answer | `AnswerRelevancyMetric` | `deepeval_answer_relevancy` |
| Completed answer vs gold reference | `GEval` | `deepeval_geval_correctness`, `deepeval_geval_completeness` |
| Answer citations vs labeled exact evidence | `GEval` | `deepeval_geval_citation_support`, `deepeval_geval_citation_coverage` |

The RAG Triad uses **bounded-context relevancy + faithfulness + answer relevancy** from the SAME captured pipeline invocation. It is not one averaged score or a separate DeepEval composite metric.

Human-reviewed chunk Precision@5, labeled Recall@5, nDCG@5 and MRR remain deterministic audit metrics, using the optional qrels file. They are prefixed `human_`; deterministic document recovery/label checks are prefixed `audit_`. These are not passed off as DeepEval semantic metrics.

## 1. Install the isolated evaluation environment

From your application repository root in Git Bash:

```bash
python --version
uv --version
uv sync --project evals/step15_deepeval --locked

uv run --project evals/step15_deepeval --locked python \
  -m unittest discover -s evals/step15_deepeval/tests -v
```

Use Python 3.12. The lock was tested with uv 0.12.23. If your uv cannot read the lock format, upgrade that installer (for example `python -m pip install "uv==0.12.23"`) rather than removing `--locked` or regenerating the application lockfile.

The environment is created inside `evals/step15_deepeval/.venv`. DeepEval requires newer Pydantic than the application's pinned version; **do not install it into your API/worker environment**. The lock has a release cutoff of 2026-10-03, matching the seven-day policy at preparation time. Keep the supplied evaluation `uv.lock` committed alongside its `pyproject.toml`.

Verified here: 17 offline checks, including executing real DeepEval metrics with scripted local API responses and replaying the original capture format into reports. These checks do not establish your real judge's quality. Live LM Studio and your laptop's Docker/provider paths still need verification.

## 2. Keep or create root `.env.evals`

If `.env.evals` already exists, retain it. The same model/base URL/revision settings work. Only add the new cache field if desired:

```dotenv
EVAL_DEEPEVAL_CACHE_DIR=evals/step15/results/deepeval-judge-cache
```

If it does not exist:

```bash
cp evals/step15_deepeval/.env.evals.example .env.evals
notepad .env.evals
```

Set:

```dotenv
EVAL_RAG_BASE_URL=http://127.0.0.1:8000
EVAL_JUDGE_BASE_URL=http://127.0.0.1:1234/v1
EVAL_JUDGE_MODEL=EXACT_ID_FROM_LM_STUDIO_V1_MODELS
EVAL_JUDGE_REVISION=GGUF_SHA256_QUANTIZATION_LM_STUDIO_VERSION
EVAL_JUDGE_API_KEY=
EVAL_DEEPEVAL_CACHE_DIR=evals/step15/results/deepeval-judge-cache
```

The revision identifies weights/quantization/runtime for caching, not an API model name. If LM Studio requires authentication, use its token as `EVAL_JUDGE_API_KEY`. Leave production Groq/OpenRouter/OpenAI settings in the application unchanged. The runner supplies the local judge object explicitly to EVERY metric; it does not let DeepEval choose a default hosted judge.

Start LM Studio with a loaded instruct model. Judge inference remains sequential, both across metrics/cases and inside the adapter. G-Eval uses schema-constrained scores rather than log-probability-weighted scoring because this adapter does not supply log probabilities. Each metric may require multiple local calls, so DeepEval can take longer on CPU than the previous custom rubrics.

The adapter accepts Pydantic schemas, validates completed JSON before caching and reports truncation/invalid outputs as evaluator errors. It never silently repairs JSON, truncates evidence or switches to a hosted judge. Configure the model context to fit the full prompt plus output budget; `EVAL_JUDGE_MAX_INPUT_BYTES` is a guard, not a tokenizer.

Verify the local adapter:

```bash
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py doctor
```

Expected: `DeepEval 4.2.8 + LM Studio schema adapter: PASSED`.

No Confident AI account/key or cloud dashboard is required. This runner measures metrics directly and writes local reports; it does not call cloud upload APIs. It disables DeepEval telemetry, sets LLM evaluation mode and keeps DeepEval's own filesystem store read-only. Its startup warning about test runs not being written refers to the framework's store; **our `summary.json`, `per-case.json`, `report.md` and cache still get written**.

## 3. If you already captured answers: rescore them now

For a one-case smoke evaluation:

```bash
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py judge \
  --captures evals/step15/results/pipeline-v1.jsonl \
  --profile core --limit 1 \
  --out evals/step15/results/deepeval-core-v1
```

Open the report and inspect reasons manually. Then complete the same profile by omitting `--limit`:

```bash
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py judge \
  --captures evals/step15/results/pipeline-v1.jsonl \
  --profile core \
  --out evals/step15/results/deepeval-core-v1
```

`core` includes built-in retrieval precision/recall/relevancy, bounded-context relevancy, faithfulness, answer relevancy and correctness G-Eval. For completeness, citations and context-budget recall, run:

```bash
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py judge \
  --captures evals/step15/results/pipeline-v1.jsonl \
  --profile full \
  --out evals/step15/results/deepeval-full-v1
```

Shared metric requests reuse the new cache. This makes **zero hosted generation calls**. Old custom score/cache files remain separate and are not interpreted as DeepEval judgments.

## 4. If you have not prepared/uploaded/captured yet

Keep FinanceBench as `../financebench/`. Select 25 questions, then upload only their required PDFs:

```bash
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py prepare --financebench ../financebench --count 25

uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py upload
```

Skip `prepare` if `evals/step15/data/golden.jsonl` already exists. Skip uploading documents already accepted/ingested; re-running upload resumes saved mappings. Review `questions.csv`, including gold answers/evidence, before scoring.

Capture three development cases first:

```bash
source scripts/dc-step12.sh

uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py capture \
  --container "$(dc12 ps -q rag-service)" \
  --mode pipeline --split dev --limit 3 \
  --revision "$(git rev-parse HEAD)-baseline-config-v1" \
  --out evals/step15/results/pipeline-v1.jsonl
```

Upload/capture commands privately prompt for the SAME dedicated test-account token with `rag:ingest` and `rag:query`. Use an otherwise empty document collection. Golden annotations remain evaluation-only; only PDFs are uploaded. Your root `.gitignore` must exclude `.env.evals`, `evals/step15/data/` and `evals/step15/results/`. The new nested ignore excludes its evaluation environment and bytecode. Retain the older nested ignore if already present.

Judge the smoke captures using section 3. Complete 20 development questions by rerunning capture without `--limit 3`, then the five held-out questions with `--split test`. The source documents are disjoint between development and test. Capture resumes completed cases, including retaining failed cases as failures; it does not automatically retry a paid/provider request. Increase pacing from the default 15 seconds if needed for your actual account limits.

Changing the evaluator does not require regeneration. Changing the generator, retrieval, corpus, prompt or context budget DOES require a new capture file/configuration revision. Captures validate source compatibility against the reviewed Step 14 implementation. A `step14_source_mismatch:<path>` must be resolved against your current source; do not edit compatibility hashes merely to bypass it.

## 5. Optional component controls and reviewed chunk labels

For generator isolation, use `capture --mode oracle --split dev --limit 5` with a new output such as `evals/step15/results/oracle-v1.jsonl`, retaining all other required capture arguments. This substitutes gold evidence through the real context builder/provider/validator for five of the same questions and adds up to five normal hosted calls. Run `judge` on that file into a separate DeepEval report. Oracle does not report artificial retrieval-quality scores.

For retriever-only capture use `--mode retriever`, with its own output. It makes no hosted generation calls; generator metrics are skipped rather than judging a placeholder answer.

To add classical metrics from reviewed chunk labels:

```bash
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py labels-template \
  --captures evals/step15/results/pipeline-v1.jsonl \
  --out evals/step15/results/reviewed-labels.json
```

Replace nulls with 0 irrelevant / 1 useful / 2 essential after inspecting each chunk. Add relevant missed chunks from an audited larger retrieval/corpus pool. Top-five-only labeling cannot establish recall of missed evidence. Then add `--labels evals/step15/results/reviewed-labels.json` to `judge` and use a new report directory for the reviewed version.

These scores stay named labeled recall because the runner cannot certify exhaustive qrels. FinanceBench annotations are evidence spans/pages, not an exhaustive chunk-level relevance map.

## Reports and interpretation

- `report.md`: means and applicable/scored denominators for dev/test/all.
- `summary.json`: versions, exact capture hash, judge identity/configuration, profile, cache/request counts and fixed G-Eval steps.
- `per-case.json`: scores, metric reasons, input scope, library implementation, application failures, evaluator errors and skipped metrics.

Metrics use `threshold=None` (score-only baseline). Set business-specific gates only after reviewing judge reliability and baseline results; default framework thresholds are not production acceptance requirements.

Generation/citation failures remain `application_completed_answer=0`; completed-answer semantic metrics are skipped, not calculated on partial failed output. Empty contexts and abstentions do not receive vacuous perfect support scores. Missing evaluator scores are N/A with explicit errors. Mean semantic scores alone must not hide application failures or coverage gaps.

Every selected original FinanceBench question is answerable. This set measures false abstentions but not abstention precision/recall. Human review of the 25 cases is still needed, especially for tables, arithmetic, units and years. The held-out five cases are a smoke check, not a precise performance estimate.

The standard graph is run in a temporary API-container subprocess with authenticated HTTP retrieval. It captures exact bounded provider input without modifying the running API. It does not test generation middleware, API-global concurrency or generation SSE; keep the Step 14 endpoint/SSE harness for those. Operational/load evaluations remain deferred.

Official references: [custom judges](https://deepeval.com/guides/guides-using-custom-llms), [contextual precision](https://deepeval.com/docs/metrics-contextual-precision), [contextual recall](https://deepeval.com/docs/metrics-contextual-recall), [faithfulness](https://deepeval.com/docs/metrics-faithfulness), [G-Eval](https://deepeval.com/docs/metrics-llm-evals).
