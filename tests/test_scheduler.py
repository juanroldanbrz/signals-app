import pytest
from src.services.scheduler import evaluate_condition


def test_above_true():
    assert evaluate_condition("above", 100.0, 101.0, None) is True

def test_above_false():
    assert evaluate_condition("above", 100.0, 99.0, None) is False

def test_above_missing_threshold():
    assert evaluate_condition("above", None, 101.0, None) is False

def test_below_true():
    assert evaluate_condition("below", 100.0, 99.0, None) is True

def test_below_false():
    assert evaluate_condition("below", 100.0, 101.0, None) is False

def test_equals_true():
    assert evaluate_condition("equals", 42.0, 42.0, None) is True

def test_equals_false():
    assert evaluate_condition("equals", 42.0, 43.0, None) is False

def test_change_true():
    assert evaluate_condition("change", None, 42.0, 40.0) is True

def test_change_false_same_value():
    assert evaluate_condition("change", None, 42.0, 42.0) is False

def test_change_false_no_last_value():
    assert evaluate_condition("change", None, 42.0, None) is False

def test_none_condition_type():
    assert evaluate_condition(None, None, 42.0, None) is False
