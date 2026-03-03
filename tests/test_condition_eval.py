import pytest
from src.services.scheduler import evaluate_condition


@pytest.mark.parametrize("condition_type,threshold,value,last_value,expected", [
    ("above", 100.0, 150.0, 100.0, True),
    ("above", 100.0, 50.0, 100.0, False),
    ("below", 100.0, 50.0, 100.0, True),
    ("below", 100.0, 150.0, 100.0, False),
    ("equals", 1.0, 1.0, 0.0, True),
    ("equals", 1.0, 0.0, 1.0, False),
    ("change", None, 200.0, 100.0, True),
    ("change", None, 100.0, 100.0, False),
    ("change", None, 100.0, None, False),
    ("above", None, 150.0, 100.0, False),   # None threshold → never alert
    (None, None, 100.0, None, False),
])
def test_evaluate_condition(condition_type, threshold, value, last_value, expected):
    result = evaluate_condition(condition_type, threshold, value, last_value)
    assert result == expected
