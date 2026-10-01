from errors.base_error import QIException


class AccountNotFound(QIException):
    code = "KOD003001"

    def __init__(self) -> None:
        super().__init__(
            "Account not found",
            self.code,
            404,
            "The account was not found.",
            "A conta não foi encontrada.",
        )