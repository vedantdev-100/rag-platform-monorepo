# Review of the 14-case run

Extract this supplement at the repository root, replacing metrics_backend.py. It adds sanitized evaluator error codes and checks that precision, faithfulness and answer-relevancy verdict counts match their inputs. DeepEval still calculates the semantic metrics. All 25 harness tests passed locally; the LM Studio judge was not rerun here.

## What was measured

Retriever: DeepEval contextual precision, contextual recall and retrieved-context relevancy. Generator: faithfulness, answer relevancy, and custom DeepEval GEval correctness/completeness/citation assessments. These component scores use pipeline captures, so generator results also depend on retrieval quality. Use oracle captures to measure the generator with gold evidence separately.

Classical chunk Precision@5, labeled Recall@5, MRR@5 and nDCG@5 are implemented but were not calculated in this report: no reviewed chunk relevance labels were supplied. Document hit rate 1.0 only means the source PDF appeared among retrieved results, not that the required passage was retrieved. Recall against an incomplete labeled pool is labeled recall, not corpus-wide recall.

## Findings

- 7 answered, 6 insufficient_context, 1 invalid_citations. Generator averages cover only 7 completed answers, not all 14 questions.
- First three captures had reversible CP1252/UTF-8 corruption. The supplied copy repairs those records only; the originals and generation outputs otherwise remain unchanged. See the SHA-256 audit. No generation calls were made.
- financebench_id_00563 used citation brackets `【S2】` instead of the required `[S2]`. This failure is preserved.
- Several abstentions retrieved unrelated passages: e.g. the largest-liability question retrieved credit concentration/assets and cash-flow passages rather than the required balance sheet. Only one captured context reached the 12,000-byte budget; increasing the budget alone is not an established fix.
- The old report records only ValueError for ten metric failures across five cases. Their exact causes cannot be recovered from those records. The patch adds diagnostic codes for future runs.
- Human judge calibration is needed: the cash-flow case received faithfulness 0 even though its supplied evidence contains the required numbers; the largest-liability case received contextual recall 1 based on a customer-deposits cash-flow mention that does not establish the largest liability.

## Rescore the repaired captures

```bash
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py judge \
  --data evals/step15/data-two-pdfs \
  --captures evals/step15/results/pipeline-two-pdfs-v1-utf8.jsonl \
  --profile full \
  --out evals/step15/results/deepeval-two-pdfs-full-v2
```

This uses the local judge and does not call the RAG generator. Keep the original report as a baseline. Inspect the new per-case error codes and reasons before accepting aggregate scores.

## Add classical retrieval metrics

```bash
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py labels-template \
  --captures evals/step15/results/pipeline-two-pdfs-v1-utf8.jsonl \
  --out evals/step15/results/two-pdfs-labels.json
```

Review each returned chunk against the question and reference evidence, replacing null grades with 0 (irrelevant), 1 (partly relevant) or 2 (directly relevant). Add known relevant chunks missing from retrieval to the per-question label pool to make recall informative; labeling only retrieved chunks cannot expose omitted relevant chunks.

Run the previous judge command again with `--labels evals/step15/results/two-pdfs-labels.json` and a fresh `--out evals/step15/results/deepeval-two-pdfs-labeled-v3`. The report then includes `human_precision_at_5`, `human_labeled_recall_at_5`, `human_mrr_at_5` and `human_ndcg_at_5`.
