from errors.base_error import QIException


class ServiceChargeNotFound(QIException):
    code = "KOD006001"

    def __init__(self) -> None:
        super().__init__(
            "Charge not found",
            self.code,
            404,
            "The charge was not found.",
            "A cobrança não foi encontrada.",
        )


class ProfessionalAccountRequired(QIException):
    code = "KOD006002"

    def __init__(self) -> None:
        super().__init__(
            "Professional account required",
            self.code,
            422,
            "Charge operations require a professional account.",
            "Operações de cobrança exigem uma conta profissional.",
        )


class InvalidChargeAmount(QIException):
    code = "KOD006003"

    def __init__(self) -> None:
        super().__init__(
            "Invalid charge amount",
            self.code,
            422,
            "The charge amount must be greater than zero.",
            "O valor da cobrança deve ser maior que zero.",
        )

class ServiceChargePaymentConflict(QIException):
    code = "KOD006004"

    def __init__(self) -> None:
        super().__init__(
            "Charge payment conflict",
            self.code,
            409,
            "The payment reference does not match an open charge, account, or amount.",
            "A referência não corresponde a uma cobrança aberta, conta ou valor.",
        )

class ChargeReceiptUnavailable(QIException):
    code = "KOD006005"

    def __init__(self) -> None:
        super().__init__(
            "Charge receipt unavailable",
            self.code,
            409,
            "The charge has not been paid yet.",
            "A cobrança ainda não foi paga.",
        )

class ChargeCancellationConflict(QIException):
    code = "KOD006006"

    def __init__(self) -> None:
        super().__init__(
            "Charge cancellation conflict",
            self.code,
            409,
            "A paid service charge cannot be canceled.",
            "Uma cobrança paga não pode ser cancelada.",
        )