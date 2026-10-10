from errors.base_error import QIException


class OwnChargePayment(QIException):
    code = "KOD007001"

    def __init__(self) -> None:
        super().__init__(
            "Own charge payment",
            self.code,
            422,
            "A client cannot pay their own service charge.",
            "O cliente não pode pagar a própria cobrança.",
        )


class ChargeAlreadyPaid(QIException):
    code = "KOD007002"

    def __init__(self) -> None:
        super().__init__(
            "Charge already paid",
            self.code,
            409,
            "The service charge has already been paid.",
            "A cobrança já foi paga.",
        )

class ChargeCanceled(QIException):
    code = "KOD007003"

    def __init__(self) -> None:
        super().__init__(
            "Charge canceled",
            self.code,
            409,
            "The service charge was canceled and cannot be paid.",
            "A cobrança foi cancelada e não pode ser paga.",
        )