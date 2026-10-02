from decimal import Decimal

import pytest

from utils.transfer_fee import calculate_transfer_fee


@pytest.mark.parametrize(
    ("amount", "source_client_id", "destination_client_id", "expected"),
    [
        ("100.00", 1, 1, "0.00"),
        ("100.00", 1, 2, "0.50"),
        ("400.00", 1, 2, "2.00"),
        ("1000.00", 1, 2, "2.00"),
        ("1.00", 1, 2, "0.01"),
        ("0.01", 1, 2, "0.00"),
    ],
)
def test_calculates_transfer_fee(
    amount, source_client_id, destination_client_id, expected
):
    fee = calculate_transfer_fee(
        Decimal(amount), source_client_id, destination_client_id
    )
    assert fee == Decimal(expected)


def test_rejects_nonpositive_amount():
    with pytest.raises(ValueError):
        calculate_transfer_fee(Decimal("0.00"), 1, 2)