"""Shared eval runner exceptions."""

from __future__ import annotations


class EvalError(RuntimeError):
    pass


class AdapterUnavailable(EvalError):
    pass


class EvalSchemaError(EvalError):
    """An answer-bearing suite or calibration file violates its documented schema."""


class CalibrationError(EvalError):
    """Judge-calibration input is inconsistent or cannot be compared."""
