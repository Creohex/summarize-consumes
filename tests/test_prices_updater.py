import pytest

from melbalabs.summarize_consumes.main import (
    cost_representation_to_int,
    query_auction,
    fetch_prices,
)


@pytest.mark.parametrize(
    ("s", "expected"),
    [
        ("", 0),
        ("0c", 0),
        ("0g0s0c", 0),
        ("1c", 1),
        ("99c", 99),
        ("1g1s1c", 10101),
        ("123g99s99c", 1239999),
    ],
)
def test_cost_representation_to_int(s, expected):
    assert cost_representation_to_int(s) == expected
