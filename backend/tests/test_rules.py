from decimal import Decimal

import pytest

from backend.app.normalization import (
    attributes,
    compare_constraint,
    identifier,
    number,
    unit,
)
from backend.app.retrieval import rrf


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1,234.56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("10,25", "10.25"),
        ("(12.50)", "-12.50"),
        ("$0.00", "0"),
        ("1 200.00", "1200.00"),
    ],
)
def test_decimal(value, expected):
    assert number(value) == Decimal(expected)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "", "abc"])
def test_bad_number(value):
    with pytest.raises(ValueError):
        number(value)


def test_normalization():
    assert identifier("ns-123/4") == "NS1234"
    assert unit("pieces") == "EA"
    assert attributes("model X1 i7 16GB RAM 512GB SSD IP65")["ram"] == "16"


def test_constraints():
    assert compare_constraint("1000 W", "1 kW") == "PASS"
    assert compare_constraint("IP65", "IP54") == "FAIL"
    assert compare_constraint("16 GB", None) == "UNKNOWN"
    assert compare_constraint("AISI316", "AISI304") == "FAIL"
    assert compare_constraint(10, 12, "GTE") == "PASS"
    assert compare_constraint("ISO9001:2015", "ISO9001:2008", "CERTIFIED_TO") == "FAIL"


def test_rrf():
    assert rrf([["a", "b"], ["b", "a"]]) == ["a", "b"]


def test_warranty_and_unknown_constraints():
    assert compare_constraint("3 years", "36 months") == "PASS"
    assert compare_constraint("IP65", "IP67") == "FAIL"
    assert compare_constraint("certificate", "certificate", "CONDITIONAL") == "UNKNOWN"
