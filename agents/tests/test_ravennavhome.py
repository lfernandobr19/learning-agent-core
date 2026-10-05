import pytest
from src.habit_score import calculate_habit_score


def test_calculate_habit_score():
    habits = [{"status": "completed", "points": 10}, {"status": "skipped", "points": 5}]
    assert calculate_habit_score(habits) == {'score': 10}

def test_invalid_input_types():
    with pytest.raises(ValueError, match="habits must be a list"):
        calculate_habit_score("not a list")

def test_invalid_status():
    with pytest.raises(ValueError, match="invalid status"):
        calculate_habit_score([{"status": "wrong", "points": 10}]):