from errors.base_error import QIException


class InvalidDepositAmount(QIException):
    code = "KOD004001"

    def __init__(self) -> None:
        super().__init__(
            "Invalid deposit amount",
            self.code,
            422,
            "The deposit amount must be greater than zero.",
            "O valor do depósito deve ser maior que zero.",
        )


class DepositReferenceConflict(QIException):
    code = "KOD004002"

    def __init__(self) -> None:
        super().__init__(
            "Deposit reference conflict",
            self.code,
            409,
            "The external reference was already used with different data.",
            "A referência externa já foi usada com dados diferentes.",
        )


class AccountBalanceLimitExceeded(QIException):
    code = "KOD004003"

    def __init__(self) -> None:
        super().__init__(
            "Account balance limit exceeded",
            self.code,
            422,
            "The resulting balance exceeds the account limit.",
            "O saldo resultante excede o limite da conta.",
        )