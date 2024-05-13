import pytest

from melbalabs.summarize_consumes.main import (
    PriceDB,
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
    assert PriceDB.cost_representation_to_int(s) == expected
