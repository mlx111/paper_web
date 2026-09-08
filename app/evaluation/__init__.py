from .types import EvaluationCase, EvaluationResult, EvaluationSummary
from .failure_classifier import classify_failure

__all__ = [
    "EvaluationRunner",
    "EvaluationCase",
    "EvaluationResult",
    "EvaluationSummary",
    "classify_failure",
]


def __getattr__(name: str):
    if name == "EvaluationRunner":
        from .runner import EvaluationRunner

        return EvaluationRunner
    raise AttributeError(name)
