# Step 15 — Run 25 FinanceBench evaluations with an LM Studio judge

Extract this ZIP into the root of your working application repository on `production-refactor`. It adds only `evals/step15/` and this guide. It does not replace application files, change dependencies, rebuild containers or migrate the database. Keep FinanceBench in its sibling directory.

This is a small, runnable baseline. The scripts use Python 3.12 standard library on the host, the existing Step 14 dependencies in the API container for generation, and your local LM Studio server for judging. No pip/uv install is required on the host.

## What this evaluates

| Mode | Path | Hosted calls |
| --- | --- | --- |
| `pipeline` | Authenticated HTTP retrieval → current standard LangGraph → existing context builder → hosted generator → existing citation validation | At most one normal generation per case, plus any fallback already enabled in your configuration |
| `retriever` | Authenticated search only; no generation | Zero |
| `oracle` | Gold evidence substituted through the same retriever interface → current context builder/generator/validation | One per case, optional |
| `judge` | Replay stored captures against LM Studio | Zero hosted calls |

The capture helper runs in a temporary subprocess inside the existing API container. It calls the running search endpoint with your test-account token and captures exactly the messages given to the provider. It does not hold a database session while judging or modify the API server. It deletes its temporary script afterward.

The graph is the production standard graph. The generation endpoint's middleware, global API concurrency and generation SSE are not exercised by this subprocess. Keep the existing Step 14 HTTP/SSE smoke harness for those checks. Run these evaluations when other hosted generation traffic is quiet, because the subprocess has its own semaphore. Retain your normal provider quotas and disable optional fallback for an unambiguous one-provider baseline.

## 1. Prerequisites

- Your Step 14 API, worker, embedding service, Docling, MinIO, PostgreSQL and Redis are working.
- A dedicated test account has `rag:ingest` and `rag:query`, with an otherwise empty document collection.
- FinanceBench is cloned next to your app: `../financebench/`.
- Python 3.12, Git and Docker are available in Git Bash.
- LM Studio has a loaded instruct model and its server is running on port 1234.

Use Qwen2.5-7B-Instruct Q4_K_M as a starter if it fits your machine. Model quality must be calibrated; downloading a larger model does not establish judge reliability. Start with the localhost server, because judging runs on the host laptop. The model's configured context must fit the judge input AND output tokens. A byte guard is provided but is not an exact token counter.

## 2. Extract and run offline checks

From the application repository root:

```bash
python --version
python -m unittest discover -s evals/step15/tests -v
source scripts/dc-step12.sh
dc12 ps
```

On host Python, 15 stdlib tests run; the six graph integration tests are skipped because host dependencies are intentionally not installed. Those six checks were run successfully here using the existing locked Step 14 environment.

The compatibility check compares installed source hashes for the Step 14 graph, context builder, provider, service, settings, retrieval service and search endpoint. If capture reports `step14_source_mismatch:<path>`, stop and send that current source file. Do not replace your working source or edit the hashes merely to suppress the check. Frontend changes do not affect these hashes.

## 3. Configure the local judge

```bash
cp evals/step15/.env.evals.example .env.evals
notepad .env.evals
```

Set these values in the **root `.env.evals`**:

```dotenv
EVAL_RAG_BASE_URL=http://127.0.0.1:8000
EVAL_JUDGE_BASE_URL=http://127.0.0.1:1234/v1
EVAL_JUDGE_MODEL=EXACT_MODEL_ID_FROM_LM_STUDIO
EVAL_JUDGE_REVISION=MODEL_FILE_HASH_QUANTIZATION_LM_STUDIO_VERSION
EVAL_JUDGE_API_KEY=
EVAL_GENERATION_INTERVAL_SECONDS=15
```

The revision is your recorded judge identity, for example a GGUF file SHA256 plus `Q4_K_M` and the LM Studio version. Change it whenever weights, quantization or runtime change. It is used in the cache key, not as the API model name.

Get the served model ID:

```bash
curl --fail http://127.0.0.1:1234/v1/models
```

If you enabled LM Studio authentication, set `EVAL_JUDGE_API_KEY` to its local API token. This is independent of Groq/OpenRouter/OpenAI keys. `.env.evals` is read by the evaluation runner only; leave production generation settings in `services/rag-service/.env` as they are. Do not put a production key in the judge field.

Make sure your **root `.gitignore`** includes:

```text
.env.evals
```

The delivered nested `.gitignore` already excludes generated data, captures, reports and caches. Keep the sibling FinanceBench PDFs outside your app repository.

Check LM Studio connectivity and schema support:

```bash
python evals/step15/run.py doctor
```

Expected: `LM Studio model and structured JSON: PASSED`. This is connectivity, not judge-quality validation. If the model cannot fit inputs, do not silently lower the evidence budget: use a supported larger context setting, explicitly reconfigure the judge, or review those cases manually. Judge truncation, missing fields and invalid evidence quotes are reported as evaluator errors.

## 4. Select exactly 25 questions

```bash
python evals/step15/run.py prepare --financebench ../financebench --count 25
```

Generated files:

- `evals/step15/data/golden.jsonl`: 25 questions, reference answers and evidence.
- `evals/step15/data/questions.csv`: readable review sheet.
- `evals/step15/data/documents.json`: required PDF paths and content hashes.
- `evals/step15/data/manifest.json`: source version, seed and dataset hash.

The selector uses seed 15, chooses enough matching documents for 20 development questions, then selects five test questions from different documents. It prioritizes documents with more available questions to keep uploads small; this is a reproducible convenience subset, not a statistically representative benchmark sample. The default current selection includes extraction, arithmetic and narrative cases, but review the CSV for suitability.

No extra unanswerable questions are generated: all 25 original FinanceBench cases are treated as answerable. This measures false abstentions, not abstention precision/recall. Those will need reviewed unanswerable cases later. A five-case held-out set is a final smoke check, not a precise generalization estimate.

The selector refuses to overwrite an existing dataset. Use a new `--out` directory for another version and pass it with `--data` to subsequent commands. If you review/change questions, create a new dataset version with a corresponding manifest rather than altering a frozen run.

## 5. Upload only the required PDFs

Log in through your existing auth API as the dedicated test account. Copy its Bearer access token, then:

```bash
python evals/step15/run.py upload
```

The script prompts privately for the token. Do not paste it into source or the guide. It uploads the required PDFs through your existing endpoint, waits sequentially for `ingested`, and stores document IDs in `document-map.json`. It does not upload gold answers, evidence annotations or evaluation JSONL.

Re-running `upload` resumes polling saved accepted uploads. If a PDF exceeds your configured upload limit, the script reports HTTP 413/other application error; inspect the API response/logs and adjust the existing upload policy if appropriate. A failed ingestion is retained for inspection. No documents or accounts are deleted automatically.

Keep this account/corpus fixed for all comparisons. Re-uploaded document IDs require a new capture output. If a token expires, log in again and rerun; the script prompts each command rather than storing the token.

## 6. Capture a three-question smoke run

```bash
source scripts/dc-step12.sh

python evals/step15/run.py capture \
  --container "$(dc12 ps -q rag-service)" \
  --mode pipeline --split dev --limit 3 \
  --revision "$(git rev-parse HEAD)-baseline-config-v1" \
  --out evals/step15/results/pipeline-v1.jsonl
```

The command prompts for the same account's token. It should print `answered`, `insufficient_context` or a saved controlled error for each case. Configure the interval to respect YOUR hosted account's throughput; 15 seconds is a conservative starting value, not a quota guarantee. Search and upload rate limits also apply. Auth/quota errors stop the run instead of retrying endlessly.

The Docker operations are launched by Python, so Git Bash does not rewrite the container `/tmp/...` paths. No `dc15` shell helper is required.

Each capture records retrieved text/IDs, exact bounded provider messages, raw output before citation validation, final answer/error, source hashes and relevant configuration. Captures contain public benchmark source text; keep them out of general application logs. The token is passed to the subprocess through stdin and never written to captures.

## 7. Judge those three locally

```bash
python evals/step15/run.py judge \
  --captures evals/step15/results/pipeline-v1.jsonl \
  --out evals/step15/results/pipeline-v1-report
```

Open `evals/step15/results/pipeline-v1-report/report.md` and `per-case.json`. Inspect the judge's extracted claims, support quotes, relevance grades, numerical correctness and reasons. Scores alone are insufficient. Verify the judge does not approve unsupported statements or confuse year/units/figures. Calibrate against human review before interpreting the rest.

## 8. Complete the 20 development cases

```bash
python evals/step15/run.py capture \
  --container "$(dc12 ps -q rag-service)" \
  --mode pipeline --split dev \
  --revision "$(git rev-parse HEAD)-baseline-config-v1" \
  --out evals/step15/results/pipeline-v1.jsonl

python evals/step15/run.py judge \
  --captures evals/step15/results/pipeline-v1.jsonl \
  --out evals/step15/results/pipeline-v1-report
```

The three already captured cases are skipped; local judgments reuse the cache. Judge requests are sequential. An invalid judgment is not assigned zero or one. Errors remain visible and the report gives scored-case denominators.

Do not append captures from changed models/prompts/settings into the same output. For every configuration change, use a new `--revision` AND new output name such as `pipeline-v2.jsonl`. The revision label must identify both the Git commit and your configuration version. The runner validates dataset/mapping/mode/top-k/revision identity on resume. It cannot infer arbitrary uncommitted changes from your chosen label.

## 9. Run the five held-out cases

After reviewing development results, freeze the chosen settings:

```bash
python evals/step15/run.py capture \
  --container "$(dc12 ps -q rag-service)" \
  --mode pipeline --split test \
  --revision "$(git rev-parse HEAD)-baseline-config-v1" \
  --out evals/step15/results/pipeline-v1.jsonl

python evals/step15/run.py judge \
  --captures evals/step15/results/pipeline-v1.jsonl \
  --out evals/step15/results/pipeline-v1-report
```

This completes exactly 25 unique questions. If settings changed after development capture, use a new capture file/configuration identity rather than mixing baselines. Reports separate `dev`, `test` and `all`.

## 10. Optional generator-only control

For five of the SAME development questions, substitute the annotated evidence while keeping the real prompt/context builder/provider/validator:

```bash
python evals/step15/run.py capture \
  --container "$(dc12 ps -q rag-service)" \
  --mode oracle --split dev --limit 5 \
  --revision "$(git rev-parse HEAD)-baseline-config-v1" \
  --out evals/step15/results/oracle-v1.jsonl

python evals/step15/run.py judge \
  --captures evals/step15/results/oracle-v1.jsonl \
  --out evals/step15/results/oracle-v1-report
```

This adds at most five normal hosted calls, not five new questions. Oracle evidence is still subject to your context budget; inspect context coverage. Good oracle answers but poor pipeline answers indicate retrieval/assembly issues; failures in both suggest prompt/model, context budget, reference quality or numerical reasoning problems. This is diagnostic evidence, not proof of the cause.

## Metrics you get

| Metric | Interpretation |
| --- | --- |
| `judge_precision_at_5` | Fraction of returned chunks judged useful, with denominator 5; not human-gold Precision@5 |
| `judge_reference_claim_recall_at_5` | Fraction of judge-extracted reference facts supported by retrieved context; not exhaustive chunk recall |
| `gold_document_hit_at_5`, `labeled_document_recall_at_5` | Deterministic recovery of the known source documents; does not prove the right passage was retrieved |
| `context_relevance` | Relevance of the EXACT bounded evidence supplied to the generator |
| `faithfulness` | Fraction of answer claims judged supported by exact context |
| `answer_relevance` | Question/answer relevance rubric, normalized 0–1 |
| `answer_correctness` | Agreement with reference, including quantities, units and periods; normalized 0–1 |
| `judge_reference_claim_context_coverage` | Reference facts surviving assembly/truncation |
| `judge_answer_completeness` | Reference facts correctly included in a successful answer |
| `citation_precision`, `citation_coverage` | Supported claim–citation associations and cited coverage of factual claims |
| `false_abstention` | Abstention on these known answerable cases |
| `pipeline_answered` | Returned a validated answer; not proof of quality |
| `supported_answer_success` | Strict smoke indicator: answered + full judged correctness/faithfulness/citation coverage. Not an industry-standard threshold |

The triad is the three separate metrics **context relevance, faithfulness/groundedness and answer relevance**. Do not average everything into a single pass score.

Judge-support quotes must exist in the exact context; that check prevents invented evidence, but quote presence alone cannot prove entailment or catch omitted claims. Human calibration remains necessary. Empty/no-claim answers have N/A support scores. Failed generation remains a failed pipeline case even when its partial/raw answer can be judged. Missing judge scores are reported separately.

## Optional human-gold Precision/Recall/ranking metrics

FinanceBench's annotated evidence is not a complete chunk-level qrels file. To calculate classical chunk metrics:

```bash
python evals/step15/run.py labels-template \
  --captures evals/step15/results/pipeline-v1.jsonl \
  --out evals/step15/results/reviewed-labels.json
```

Replace every `null` with **0 irrelevant / 1 useful / 2 essential**, after reviewing the actual chunk. Add known relevant chunks missed by retrieval to the same case's dictionary. Use search at a larger `top_k` or an audited corpus export to form the labeling pool; top-five-only labels cannot establish recall over the corpus. Freeze relevance judgments against the corpus/chunking snapshot.

```bash
python evals/step15/run.py judge \
  --captures evals/step15/results/pipeline-v1.jsonl \
  --labels evals/step15/results/reviewed-labels.json \
  --out evals/step15/results/pipeline-v1-reviewed-report
```

This adds human-reviewed `precision_at_5`, `labeled_recall_at_5`, `ndcg_at_5` and `mrr_at_5`. Recall remains named labeled recall because the runner cannot certify exhaustive labels. No-positive cases have N/A recall/nDCG/MRR. Unfilled labels stop scoring instead of being silently treated as irrelevant. These extra label entries do not create new questions.

## Failures and resume

- **401/403:** get a fresh correctly scoped token for the SAME test account. Recorded cases are not retried automatically.
- **429/provider quota:** increase pacing or wait until quota resets. A failed saved case remains a failure. Use a separate output for an explicit retry so the first failure is preserved.
- **Source mismatch:** send the named current source file; no production code is overwritten.
- **Incomplete judge output:** increase the verified output/context capacity or review manually, then rerun judging. Failed judgments are not cached as successes.
- **Judge/model change:** update `EVAL_JUDGE_MODEL`/`EVAL_JUDGE_REVISION` and use a new report directory. No hosted regeneration is needed to rescore unchanged captures.
- **Upload timeout:** rerun upload; accepted IDs were saved before polling.
- **Parser/embedding/corpus/generation changes:** use a new dataset/capture configuration and freeze its document mapping. The existing results are a baseline, not live mutable state.

## Verification and scope

Verified here: 15 host unit checks plus six tests through the installed real Step 14 LangGraph, including exact bounded input capture, invalid citations, no-evidence abstention, authentication rejection, oracle control and no-generation retrieval mode. Real FinanceBench question metadata and PDF filename inventory were checked for selection; benchmark PDFs were not parsed in this environment. Docker, your hosted provider, database and actual LM Studio judge must be verified on your laptop.

This first harness uses custom versioned rubrics through an OpenAI-compatible judge adapter, not Ragas or TruLens dependency packages. Its scores must not be presented as their official metric implementations. It adds no operations evaluation, multi-hop graph ingestion, Corrective RAG or Self-RAG loops.

After running, send `summary.json` and a few failed case records without tokens or credentials. We can use those results to choose the next quality improvements.

Official references: [FinanceBench](https://github.com/patronus-ai/financebench), [LM Studio server](https://lmstudio.ai/docs/developer/core/server), [structured outputs](https://lmstudio.ai/docs/developer/openai-compat/structured-output), [RAG Triad](https://www.trulens.org/getting_started/core_concepts/rag_triad/).
