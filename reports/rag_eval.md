# RAG evaluation

Questions: 75 answerable, 12 unanswerable. Settings: `RAG_MIN_VECTOR_SCORE=0.4`, pool `20`, rerank pool `10`.

Query planner (one LLM call): {'median_s': 2.81, 'failed': 0}

## Retrieval by query mode (`plan` = the planner's standalone question + its HyDE passage)

| mode | hit@1 | hit@5 | hit@10 | hit@20 | MRR | MRR vi | MRR en | MRR follow-up | hit@5 vi | hit@5 en | hit@5 follow-up |
|---|---|---|---|---|---|---|---|---|---|---|---|
| raw | 0.267 | 0.52 | 0.667 | 0.813 | 0.387 | 0.38 | 0.398 | 0.033 | 0.511 | 0.533 | 0.0 |
| both | 0.333 | 0.6 | 0.72 | 0.827 | 0.444 | 0.446 | 0.441 | 0.019 | 0.622 | 0.567 | 0.0 |
| plan | 0.307 | 0.587 | 0.773 | 0.84 | 0.443 | 0.461 | 0.417 | 0.4 | 0.622 | 0.533 | 0.667 |

## Reranking of `plan` candidates (top 5 after the cross-encoder, 1000 chars; presets in RERANK_PRESETS)

| preset | hit@1 | hit@5 | MRR | MRR vi | MRR en | MRR follow-up | hit@5 vi | hit@5 en | hit@5 follow-up | median s | reranker used |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| single10 | 0.453 | 0.653 | 0.531 | 0.422 | 0.694 | 0.067 | 0.578 | 0.767 | 0.333 | 4.21 | True |
| no_rerank_fused_order | 0.307 | 0.587 | 0.412 | 0.437 | 0.376 | 0.4 | 0.622 | 0.533 | 0.667 | - | - |

### Refusal gate on the reranker score (`single10`): best score of answerable vs out-of-domain questions

answerable min/median [0.0, 0.6098], out-of-domain median/max [0.0002, 0.0783]

| min rerank score | answerable rejected | unanswerable accepted |
|---|---|---|
| 0.005 | 0.2 | 0.25 |
| 0.01 | 0.267 | 0.083 |
| 0.02 | 0.333 | 0.083 |
| 0.05 | 0.36 | 0.083 |
| 0.1 | 0.4 | 0.0 |
| 0.2 | 0.4 | 0.0 |
| 0.3 | 0.427 | 0.0 |
| 0.5 | 0.44 | 0.0 |

## Relevance threshold on the cosine score (answerable rejected / out-of-domain accepted)

`raw`: {'answerable_min/median': [0.247, 0.448], 'unanswerable_median/max': [0.147, 0.213]}

| threshold | answerable rejected | unanswerable accepted |
|---|---|---|
| 0.20 | 0.0 | 0.167 |
| 0.25 | 0.013 | 0.0 |
| 0.30 | 0.053 | 0.0 |
| 0.35 | 0.147 | 0.0 |
| 0.40 | 0.293 | 0.0 |
| 0.45 | 0.52 | 0.0 |
| 0.50 | 0.573 | 0.0 |

`both`: {'answerable_min/median': [0.311, 0.634], 'unanswerable_median/max': [0.202, 0.355]}

| threshold | answerable rejected | unanswerable accepted |
|---|---|---|
| 0.20 | 0.0 | 0.5 |
| 0.25 | 0.0 | 0.25 |
| 0.30 | 0.0 | 0.167 |
| 0.35 | 0.013 | 0.083 |
| 0.40 | 0.04 | 0.0 |
| 0.45 | 0.12 | 0.0 |
| 0.50 | 0.173 | 0.0 |

`plan`: {'answerable_min/median': [0.358, 0.669], 'unanswerable_median/max': [0.173, 0.286]}

| threshold | answerable rejected | unanswerable accepted |
|---|---|---|
| 0.20 | 0.0 | 0.417 |
| 0.25 | 0.0 | 0.083 |
| 0.30 | 0.0 | 0.0 |
| 0.35 | 0.0 | 0.0 |
| 0.40 | 0.013 | 0.0 |
| 0.45 | 0.027 | 0.0 |
| 0.50 | 0.107 | 0.0 |

## Answers

```json
{
  "questions": 30,
  "answered": 28,
  "not_found_on_answerable": 2,
  "cited_rate": 1.0,
  "numbers_supported_rate": 1.0,
  "judge_supported_mean": 0.661,
  "correct_refusals_on_unanswerable": "12/12"
}
```
