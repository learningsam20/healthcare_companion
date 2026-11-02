"""DeepEval adapter for non-RAG suites.

Optional: the dependency is not part of the base install. The judge must be a
LiteLLM-backed model so no eval call bypasses the gateway. Cases must carry
input/actual_output/expected_output/retrieval_context fields.
"""

from __future__ import annotations

import inspect
import os
import tempfile
from typing import Any

from evals.harness.errors import AdapterUnavailable, EvalError


def _judge_model(judge_alias: str) -> Any:
    from deepeval.models import LiteLLMModel

    base_url = os.environ.get("LITELLM_BASE_URL", "http://litellm:4000").rstrip("/")
    api_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not api_key:
        raise AdapterUnavailable(
            "LITELLM_MASTER_KEY is required so judge calls go through the gateway"
        )
    parameters = inspect.signature(LiteLLMModel).parameters
    # LiteLLM needs a provider prefix even when the target is an OpenAI-compatible
    # gateway; the prefix is stripped before the request reaches LiteLLM.
    kwargs: dict[str, Any] = {"model": f"openai/{judge_alias}"}
    if "base_url" in parameters:
        kwargs["base_url"] = f"{base_url}/v1"
    if "api_key" in parameters:
        kwargs["api_key"] = api_key
    if "base_url" not in parameters or "api_key" not in parameters:
        raise AdapterUnavailable(
            "the installed DeepEval LiteLLMModel cannot be pointed at LiteLLM; "
            "upgrade deepeval or wire the gateway before running this framework"
        )
    return LiteLLMModel(**kwargs)


def run(cases: list[dict[str, Any]], *, judge_alias: str) -> dict[str, Any]:
    # DeepEval stores local settings under this folder. Containers run with a
    # read-only root filesystem, so the default relative ".deepeval" is unwritable.
    os.environ.setdefault("DEEPEVAL_CACHE_FOLDER", tempfile.mkdtemp(prefix="sahyog-deepeval-"))
    try:
        from deepeval.metrics import (
            AnswerRelevancyMetric,
            ContextualPrecisionMetric,
            ContextualRecallMetric,
            FaithfulnessMetric,
        )
        from deepeval.test_case import LLMTestCase
    except ImportError as exc:
        raise AdapterUnavailable(
            "DeepEval adapter dependencies are not installed; add the optional eval "
            f"dependencies (deepeval) before running it: {exc}"
        ) from exc

    required = ("input", "actual_output", "expected_output", "retrieval_context")
    for case in cases:
        missing = {field for field in required if field not in case}
        if missing:
            raise EvalError(
                f"case {case['id']} lacks DeepEval fields: {', '.join(sorted(missing))}"
            )

    judge = _judge_model(judge_alias)
    metrics = {
        "answer_relevancy": AnswerRelevancyMetric(model=judge),
        "faithfulness": FaithfulnessMetric(model=judge),
        "contextual_precision": ContextualPrecisionMetric(model=judge),
        "contextual_recall": ContextualRecallMetric(model=judge),
    }
    scores: dict[str, list[float]] = {name: [] for name in metrics}
    case_results: list[dict[str, Any]] = []
    for case in cases:
        test_case = LLMTestCase(
            input=case["input"],
            actual_output=case["actual_output"],
            expected_output=case["expected_output"],
            retrieval_context=list(case["retrieval_context"]),
        )
        case_scores: dict[str, float] = {}
        failures: list[str] = []
        for name, metric in metrics.items():
            try:
                metric.measure(test_case)
            except Exception as exc:  # the adapter must not hide judge failures
                raise EvalError(f"DeepEval metric {name} failed on {case['id']}: {exc}") from exc
            score = float(metric.score or 0.0)
            case_scores[name] = score
            scores[name].append(score)
            threshold = float(getattr(metric, "threshold", 0.0) or 0.0)
            if score < threshold:
                failures.append(f"{name} {score:.3f} below {threshold:.3f}")
        case_results.append(
            {
                "id": case["id"],
                "check": "deepeval",
                "passed": not failures,
                "failures": failures,
                "scores": case_scores,
            }
        )
    aggregated = {
        name: round(sum(values) / len(values), 6) for name, values in scores.items() if values
    }
    return {"metrics": aggregated, "cases": case_results}
