from errors.base_error import QIException


class InvalidTransferAmount(QIException):
    code = "KOD005001"

    def __init__(self) -> None:
        super().__init__(
            "Invalid transfer amount",
            self.code,
            422,
            "The transfer amount must be greater than zero.",
            "O valor da transferência deve ser maior que zero.",
        )


class SameAccountTransfer(QIException):
    code = "KOD005002"

    def __init__(self) -> None:
        super().__init__(
            "Same account transfer",
            self.code,
            422,
            "The source and destination accounts must be different.",
            "A conta de origem e a de destino devem ser diferentes.",
        )


class TransferIdempotencyConflict(QIException):
    code = "KOD005003"

    def __init__(self) -> None:
        super().__init__(
            "Transfer idempotency conflict",
            self.code,
            409,
            "The idempotency key was already used with different transfer data.",
            "A chave de idempotência já foi usada com outros dados.",
        )


class TransferNotFound(QIException):
    code = "KOD005004"

    def __init__(self) -> None:
        super().__init__(
            "Transfer not found",
            self.code,
            404,
            "The transfer was not found.",
            "A transferência não foi encontrada.",
        )