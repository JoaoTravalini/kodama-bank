from errors.base_error import QIException


class InvalidClientDocument(QIException):
    code = "KOD001001"

    def __init__(self):
        super().__init__(
            "Invalid CPF", self.code, 422,
            "The CPF is invalid.",
            "O CPF informado é inválido.",
        )


class ClientDocumentAlreadyRegistered(QIException):
    code = "KOD001002"

    def __init__(self):
        super().__init__(
            "CPF already registered", self.code, 409,
            "CPF already registered.",
            "CPF já cadastrado.",
        )


class ClientEmailAlreadyRegistered(QIException):
    code = "KOD001003"

    def __init__(self):
        super().__init__(
            "Email already registered", self.code, 409,
            "Email already registered.",
            "E-mail já cadastrado.",
        )