"""RAGAS adapter for RAG suites.

Optional: the dependency is not part of the base install. Every judge and embedding
call is routed through the LiteLLM proxy; the adapter never talks to a provider
directly. Cases must carry question/answer/contexts/ground_truth fields.
"""

from __future__ import annotations

import os
from typing import Any

from evals.harness.errors import AdapterUnavailable, EvalError


def _gateway() -> tuple[str, str]:
    base_url = os.environ.get("LITELLM_BASE_URL", "http://litellm:4000").rstrip("/")
    api_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not api_key:
        raise AdapterUnavailable(
            "LITELLM_MASTER_KEY is required so judge calls go through the gateway"
        )
    return f"{base_url}/v1", api_key


def _embedding_alias() -> str:
    return os.environ.get("EVAL_EMBEDDING_ALIAS", "local_embedding")


def run(cases: list[dict[str, Any]], *, judge_alias: str) -> dict[str, Any]:
    try:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas import EvaluationDataset, evaluate

        # Ragas 0.4 keeps the metric objects that `evaluate` validates in the
        # classic modules; the `metrics.collections` API is not a Metric subclass.
        from ragas.metrics._answer_relevance import answer_relevancy
        from ragas.metrics._context_precision import context_precision
        from ragas.metrics._context_recall import context_recall
        from ragas.metrics._faithfulness import faithfulness
        from ragas.run_config import RunConfig
    except ImportError as exc:
        raise AdapterUnavailable(
            "RAGAS adapter dependencies are not installed; add the optional eval "
            f"dependencies (ragas, langchain-openai) before running it: {exc}"
        ) from exc

    rows: list[dict[str, Any]] = []
    for case in cases:
        missing = {
            field
            for field in ("question", "answer", "contexts", "ground_truth")
            if field not in case
        }
        if missing:
            raise EvalError(f"case {case['id']} lacks RAGAS fields: {', '.join(sorted(missing))}")
        rows.append(
            {
                "user_input": case["question"],
                "response": case["answer"],
                "retrieved_contexts": list(case["contexts"]),
                "reference": case["ground_truth"],
            }
        )

    base_url, api_key = _gateway()
    judge = ChatOpenAI(model=judge_alias, base_url=base_url, api_key=api_key, temperature=0)
    embeddings = OpenAIEmbeddings(model=_embedding_alias(), base_url=base_url, api_key=api_key)
    dataset = EvaluationDataset.from_list(rows)
    # The default 16 workers saturates a local 7B Ollama judge and trips the
    # gateway's request timeout; two workers keep a full suite inside budget.
    run_config = RunConfig(timeout=600, max_retries=2, max_wait=30, max_workers=2)
    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=judge,
        embeddings=embeddings,
        run_config=run_config,
        raise_exceptions=True,
    )
    frame = result.to_pandas()
    metrics = {
        metric: round(float(frame[metric].mean()), 6)
        for metric in ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
        if metric in frame
    }
    case_results = []
    for index, case in enumerate(cases):
        case_results.append(
            {
                "id": case["id"],
                "check": "ragas",
                "passed": True,
                "failures": [],
                "scores": {metric: float(frame.iloc[index][metric]) for metric in metrics},
            }
        )
    return {"metrics": metrics, "cases": case_results}
