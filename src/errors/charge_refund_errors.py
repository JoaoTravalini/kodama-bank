from errors.base_error import QIException


class RefundUnavailable(QIException):
    code = "KOD008001"

    def __init__(self) -> None:
        super().__init__(
            "Refund unavailable",
            self.code,
            409,
            "Only charges paid by a completed Kodama transfer can be refunded.",
            "Somente cobranças pagas por transferência concluída no Kodama podem ser estornadas.",
        )


class ChargeAlreadyRefunded(QIException):
    code = "KOD008002"

    def __init__(self) -> None:
        super().__init__(
            "Charge already refunded",
            self.code,
            409,
            "The service charge has already been refunded.",
            "A cobrança já foi estornada.",
        )


class ChargeRefundNotFound(QIException):
    code = "KOD008003"

    def __init__(self) -> None:
        super().__init__(
            "Refund not found",
            self.code,
            404,
            "The refund was not found.",
            "O estorno não foi encontrado.",
        )

class ChargeRefundReceiptUnavailable(QIException):
    code = "KOD008004"

    def __init__(self) -> None:
        super().__init__(
            "Refund receipt unavailable",
            self.code,
            409,
            "A receipt is available only after the refund is completed.",
            "O comprovante fica disponível somente após a conclusão do estorno.",
        )