from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
RATE = Decimal("0.005")  # 0,5%
FEE_LIMIT = Decimal("2.00")
ZERO = Decimal("0.00")


def calculate_transfer_fee(
    amount: Decimal,
    source_client_id: int,
    destination_client_id: int,
) -> Decimal:
    if amount <= 0:
        raise ValueError("O valor da transferência deve ser positivo.")

    if source_client_id == destination_client_id:
        return ZERO

    fee = (amount * RATE).quantize(CENT, rounding=ROUND_HALF_UP)
    return min(fee, FEE_LIMIT)