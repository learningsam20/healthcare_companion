from __future__ import annotations

from sahyog_common.errors import ProblemError


def test_problem_error_is_raisable_with_detail() -> None:
    error = ProblemError(403, "forbidden", "Forbidden", "Not allowed")
    assert isinstance(error, Exception)
    assert str(error) == "Not allowed"

    try:
        raise error
    except ProblemError as caught:
        assert caught.code == "forbidden"
        assert caught.to_problem("/records")["instance"] == "/records"
